#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SD-Core AMF service."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires  # type: ignore[import]
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
)
from charms.prometheus_k8s.v0.prometheus_scrape import (  # type: ignore[import]
    MetricsEndpointProvider,
)
from charms.sdcore_nrf.v0.fiveg_nrf import NRFRequires  # type: ignore[import]
from jinja2 import Environment, FileSystemLoader
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, EventBase, RelationJoinedEvent
from ops.main import main
from ops.model import (
    ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus, ModelError
)
from ops.pebble import Layer

from lib.charms.sdcore_amf.v0.fiveg_n2 import N2Provides  # type: ignore[import]

logger = logging.getLogger(__name__)

PROMETHEUS_PORT = 9089
SBI_PORT = 29518
NGAPP_PORT = 38412
SCTP_GRPC_PORT = 9000
DATABASE_NAME = "sdcore_amf"
CONFIG_DIR_PATH = "/free5gc/config"
CONFIG_FILE_NAME = "amfcfg.conf"
CONFIG_TEMPLATE_DIR_PATH = "src/templates/"
CONFIG_TEMPLATE_NAME = "amfcfg.conf.j2"
CORE_NETWORK_FULL_NAME = "SDCORE5G"
CORE_NETWORK_SHORT_NAME = "SDCORE"
N2_RELATION_NAME = "fiveg-n2"


class AMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the SD-Core AMF operator."""

    def __init__(self, *args):
        super().__init__(*args)
        self._amf_container_name = self._amf_service_name = "amf"
        self._amf_container = self.unit.get_container(self._amf_container_name)
        self._nrf_requires = NRFRequires(charm=self, relation_name="fiveg_nrf")
        self.n2_provider = N2Provides(self, N2_RELATION_NAME)
        self._amf_metrics_endpoint = MetricsEndpointProvider(self)
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="prometheus-exporter", port=PROMETHEUS_PORT),
                ServicePort(name="sbi", port=SBI_PORT),
                ServicePort(name="ngapp", port=NGAPP_PORT, protocol="SCTP"),
                ServicePort(name="sctp-grpc", port=SCTP_GRPC_PORT),
            ],
        )
        self._database = DatabaseRequires(
            self, relation_name="database", database_name=DATABASE_NAME
        )
        self.framework.observe(self.on.database_relation_joined, self._configure_amf)
        self.framework.observe(self._database.on.database_created, self._configure_amf)
        self.framework.observe(self.on.amf_pebble_ready, self._configure_amf)
        self.framework.observe(self._nrf_requires.on.nrf_available, self._configure_amf)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._set_n2_information)

    def _configure_amf(
        self,
        event: EventBase,
    ) -> None:
        """Handle pebble ready event for AMF container.

        Args:
            event (PebbleReadyEvent, DatabaseCreatedEvent, NRFAvailableEvent): Juju event
        """
        if not self._amf_container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for service to start")
            event.defer()
            return
        for relation in ["fiveg_nrf", "database"]:
            if not self._relation_created(relation):
                self.unit.status = BlockedStatus(f"Waiting for {relation} relation")
                return
        if not self._database_is_available():
            self.unit.status = WaitingStatus("Waiting for the amf database to be available")
            event.defer()
            return
        if not self._get_database_info():
            self.unit.status = WaitingStatus("Waiting for AMF database info to be available")
            event.defer()
            return
        if not self._nrf_requires.nrf_url:
            self.unit.status = WaitingStatus("Waiting for NRF data to be available")
            event.defer()
            return
        if not self._amf_container.exists(path=CONFIG_DIR_PATH):
            self.unit.status = WaitingStatus("Waiting for storage to be attached")
            event.defer()
            return
        self._generate_config_file()
        self._configure_amf_workload()
        self._set_n2_information(event=event)
        self.unit.status = ActiveStatus()

    def _set_n2_information(self, event: RelationJoinedEvent):
        if not self._relation_created(N2_RELATION_NAME):
            return
        if not self.unit.is_leader():
            return
        if not self._amf_service_is_running():
            return
        self.n2_provider.set_n2_information(
            amf_ip_address=_get_pod_ip(),
            amf_hostname=self._amf_hostname(),
            amf_port=NGAPP_PORT,
        )

    def _generate_config_file(self) -> None:
        """Handles creation of the AMF config file.

        Generates AMF config file based on a given template.
        Pushes AMF config file to the workload.
        Calls `_configure_amf_workload` function to forcibly restart the AMF service in order
        to fetch new config.
        """
        content = self._render_config_file(
            ngapp_port=NGAPP_PORT,
            sctp_grpc_port=SCTP_GRPC_PORT,
            sbi_port=SBI_PORT,
            nrf_url=self._nrf_requires.nrf_url,
            amf_ip=_get_pod_ip(),
            database_name=DATABASE_NAME,
            database_url=self._get_database_info()["uris"].split(",")[0],
            full_network_name=CORE_NETWORK_FULL_NAME,
            short_network_name=CORE_NETWORK_SHORT_NAME,
        )
        if not self._config_file_content_matches(content=content):
            self._push_config_file(
                content=content,
            )
            self._configure_amf_workload(restart=True)

    @staticmethod
    def _render_config_file(
        *,
        database_name: str,
        amf_ip: str,
        ngapp_port: int,
        sctp_grpc_port: int,
        sbi_port: int,
        nrf_url: str,
        database_url: str,
        full_network_name: str,
        short_network_name: str,
    ) -> str:
        """Renders the AMF config file.

        Args:
            database_name (str): Name of the AMF database.
            amf_ip (str): IP address of the AMF.
            ngapp_port (int): AMF NGAP port.
            sctp_grpc_port (int): AMF SCTP port.
            sbi_port (int): AMF SBi port.
            nrf_url (str): URL of the NRF.
            database_url (str): URL of the AMF database.
            full_network_name (str): Full name of the network.
            short_network_name (str): Short name of the network.

        Returns:
            str: Content of the rendered config file.
        """
        jinja2_environment = Environment(loader=FileSystemLoader(CONFIG_TEMPLATE_DIR_PATH))
        template = jinja2_environment.get_template(CONFIG_TEMPLATE_NAME)
        content = template.render(
            ngapp_port=ngapp_port,
            sctp_grpc_port=sctp_grpc_port,
            sbi_port=sbi_port,
            nrf_url=nrf_url,
            amf_ip=amf_ip,
            database_name=database_name,
            database_url=database_url,
            full_network_name=full_network_name,
            short_network_name=short_network_name,
        )
        return content

    def _push_config_file(self, content: str) -> None:
        """Writes the AMF config file and pushes it to the container.

        Args:
            content (str): Content of the config file.
        """
        self._amf_container.push(
            path=f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",
            source=content,
        )
        logger.info("Pushed %s config file", CONFIG_FILE_NAME)

    def _relation_created(self, relation_name: str) -> bool:
        """Returns True if the relation is created, False otherwise.

        Args:
            relation_name (str): Name of the relation.

        Returns:
            bool: True if the relation is created, False otherwise.
        """
        return bool(self.model.get_relation(relation_name))

    def _configure_amf_workload(self, restart: bool = False) -> None:
        """Configures pebble layer for the amf container.

        Args:
            restart (bool): Whether to restart the amf container.
        """
        plan = self._amf_container.get_plan()
        layer = self._amf_pebble_layer
        if plan.services != layer.services or restart:
            self._amf_container.add_layer("amf", layer, combine=True)
            self._amf_container.restart(self._amf_service_name)

    def _config_file_content_matches(self, content: str) -> bool:
        """Returns whether the amfcfg config file content matches the provided content.

        Returns:
            bool: Whether the amfcfg config file content matches
        """
        if not self._amf_container.exists(path=f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}"):
            return False
        existing_content = self._amf_container.pull(path=f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}")
        if existing_content.read() != content:
            return False
        return True

    @property
    def _amf_pebble_layer(self) -> Layer:
        """Returns pebble layer for the amf container.

        Returns:
            Layer: Pebble Layer
        """
        return Layer(
            {
                "services": {
                    self._amf_service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": f"/free5gc/amf/amf --amfcfg {CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",  # noqa: E501
                        "environment": self._amf_environment_variables,
                    },
                },
            }
        )

    def _get_database_info(self) -> dict:
        """Returns the database data.

        Returns:
            Dict: The database data.
        """
        if not self._database_is_available():
            raise RuntimeError(f"Database `{DATABASE_NAME}` is not available")
        return self._database.fetch_relation_data()[self._database.relations[0].id]

    def _database_is_available(self) -> bool:
        """Returns True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._database.is_resource_created()

    @property
    def _amf_environment_variables(self) -> dict:
        """Returns environment variables for the amf container.

        Returns:
            dict: Environment variables.
        """
        return {
            "GOTRACEBACK": "crash",
            "GRPC_GO_LOG_VERBOSITY_LEVEL": "99",
            "GRPC_GO_LOG_SEVERITY_LEVEL": "info",
            "GRPC_TRACE": "all",
            "GRPC_VERBOSITY": "DEBUG",
            "POD_IP": _get_pod_ip(),
            "MANAGED_BY_CONFIG_POD": "true",
        }

    def _amf_hostname(self) -> str:
        """Builds and returns the AMF hostname in the cluster.
        Returns:
            str: The AMF hostname.
        """
        return f"{self.model.app.name}.{self.model.name}.svc.cluster.local"

    def _amf_service_is_running(self) -> bool:
        """Returns whether the AMF service is running.

        Returns:
            bool: Whether the AMF service is running.
        """
        if not self._amf_container.can_connect():
            return False
        try:
            service = self._amf_container.get_service(self._amf_service_name)
        except ModelError:
            return False
        return service.is_running()


def _get_pod_ip() -> str:
    """Returns the pod IP using juju client.

    Returns:
        str: The pod IP.
    """
    return str(IPv4Address(check_output(["unit-get", "private-address"]).decode().strip()))


if __name__ == "__main__":  # pragma: no cover
    main(AMFOperatorCharm)
