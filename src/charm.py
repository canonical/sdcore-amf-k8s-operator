#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SDCORE AMF service."""

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
from ops.charm import CharmBase, EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)

PROMETHEUS_PORT = 9089
SBI_PORT = 29518
NGAPP_PORT = 38412
SCTP_GRPC_PORT = 9000
AMF_DATABASE_NAME = "sdcore_amf"
DEFAULT_DATABASE_NAME = "free5gc"
CONFIG_DIR_PATH = "/free5gc/config"
CONFIG_FILE_NAME = "amfcfg.conf"
CONFIG_TEMPLATE_DIR_PATH = "src/templates/"
CONFIG_TEMPLATE_NAME = "amfcfg.conf.j2"


class AMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the 5G AMF operator."""

    def __init__(self, *args):
        super().__init__(*args)
        self._amf_container_name = self._amf_service_name = "amf"
        self._amf_container = self.unit.get_container(self._amf_container_name)
        self._nrf_requires = NRFRequires(charm=self, relation_name="fiveg_nrf")
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
        self._amf_database = DatabaseRequires(
            self, relation_name="amf-database", database_name=AMF_DATABASE_NAME
        )
        self._default_database = DatabaseRequires(
            self, relation_name="default-database", database_name=DEFAULT_DATABASE_NAME
        )

        self.framework.observe(
            self.on.default_database_relation_joined,
            self._on_amf_pebble_ready,
        )
        self.framework.observe(
            self.on.amf_database_relation_joined,
            self._on_amf_pebble_ready,
        )
        self.framework.observe(
            self._default_database.on.database_created, self._on_amf_pebble_ready
        )
        self.framework.observe(self._amf_database.on.database_created, self._on_amf_pebble_ready)
        self.framework.observe(self.on.amf_pebble_ready, self._on_amf_pebble_ready)
        self.framework.observe(self._nrf_requires.on.nrf_available, self._on_amf_pebble_ready)

    def _on_amf_pebble_ready(
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
        for relation in ["fiveg_nrf", "amf-database", "default-database"]:
            if not self._relation_created(relation):
                self.unit.status = BlockedStatus(f"Waiting for {relation} relation")
                return
        if not self._default_database_is_available:
            self.unit.status = WaitingStatus("Waiting for the default database to be available")
            event.defer()
            return
        if not self._amf_database_is_available:
            self.unit.status = WaitingStatus("Waiting for the amf database to be available")
            event.defer()
            return
        if not self._default_database_info:
            self.unit.status = WaitingStatus("Waiting for default database info to be available")
            event.defer()
            return
        if not self._nrf_data_is_available:
            self.unit.status = WaitingStatus("Waiting for NRF data to be available")
            event.defer()
            return
        if not self._config_file_is_pushed:
            self._push_config_file(
                ngapp_port=NGAPP_PORT,
                sctp_grpc_port=SCTP_GRPC_PORT,
                sbi_port=SBI_PORT,
                nrf_url=self._nrf_requires.nrf_url,
                amf_url=self._amf_hostname,
                default_database_name=DEFAULT_DATABASE_NAME,
                amf_database_name=AMF_DATABASE_NAME,
                database_url=self._default_database_info["uris"].split(",")[0],
            )
        self._amf_container.add_layer("amf", self._amf_pebble_layer, combine=True)
        self.unit.status = ActiveStatus()

    def _push_config_file(
        self,
        default_database_name: str,
        amf_database_name: str,
        amf_url: str,
        ngapp_port: int,
        sctp_grpc_port: int,
        sbi_port: int,
        nrf_url: str,
        database_url: str,
    ) -> None:
        """Writes the AMF config file and pushes it to the container.

        Args:
            default_database_name (str): Name of the default (free5gc) database.
            amf_database_name (str): Name of the AMF database.
            amf_url (str): URL of the AMF.
            ngapp_port (int): AMF NGAP port.
            sctp_grpc_port (int): AMF SCTP port.
            sbi_port (int): AMF SBi port.
            database_url (str): URL of the default (free5gc) database.
            nrf_url (str): URL of the NRF.
        """
        jinja2_environment = Environment(loader=FileSystemLoader(CONFIG_TEMPLATE_DIR_PATH))
        template = jinja2_environment.get_template(CONFIG_TEMPLATE_NAME)
        content = template.render(
            ngapp_port=ngapp_port,
            sctp_grpc_port=sctp_grpc_port,
            sbi_port=sbi_port,
            nrf_url=nrf_url,
            amf_url=amf_url,
            default_database_name=default_database_name,
            amf_database_name=amf_database_name,
            database_url=database_url,
        )
        self._amf_container.push(
            path=f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",
            source=content,
            make_dirs=True,
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

    @property
    def _default_database_info(self) -> dict:
        """Returns the database data.

        Returns:
            Dict: The database data.
        """
        if not self._default_database_is_available:
            None
        return self._default_database.fetch_relation_data()[self._default_database.relations[0].id]

    @property
    def _default_database_is_available(self) -> bool:
        """Returns True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._default_database.is_resource_created()

    @property
    def _amf_database_is_available(self) -> bool:
        """Returns True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._amf_database.is_resource_created()

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
            "POD_IP": self._pod_ip,
            "MANAGED_BY_CONFIG_POD": "true",
        }

    @property
    def _pod_ip(
        self,
    ) -> str:
        """Returns the pod IP using juju client.

        Returns:
            str: The pod IP.
        """
        return str(IPv4Address(check_output(["unit-get", "private-address"]).decode().strip()))

    @property
    def _config_file_is_pushed(self) -> bool:
        """Returns whether the config file is pushed to the container.

        Returns:
            bool: Whether the config file is pushed.
        """
        if not self._amf_container.exists(f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}"):
            logger.info("%s Config file is not pushed", CONFIG_FILE_NAME)
            return False
        logger.info("Config file is pushed")
        return True

    @property
    def _nrf_data_is_available(self) -> bool:
        """Returns whether the NRF data is available.

        Returns:
            bool: Whether the NRF data is available.
        """
        if not self._nrf_requires.nrf_url:
            return False
        return True

    @property
    def _amf_hostname(self) -> str:
        """Builds and returns the AMF hostname in the cluster.

        Returns:
            str: The AMF hostname.
        """
        return f"{self.model.app.name}.{self.model.name}.svc.cluster.local"


if __name__ == "__main__":
    main(AMFOperatorCharm)
