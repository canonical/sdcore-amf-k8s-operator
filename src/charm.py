#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SD-Core AMF service."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output
from typing import Optional

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires  # type: ignore[import]
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
)
from charms.prometheus_k8s.v0.prometheus_scrape import (  # type: ignore[import]
    MetricsEndpointProvider,
)
from charms.sdcore_amf.v0.fiveg_n2 import N2Provides  # type: ignore[import]
from charms.sdcore_nrf.v0.fiveg_nrf import NRFRequires  # type: ignore[import]
from charms.tls_certificates_interface.v2.tls_certificates import (  # type: ignore[import]
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    TLSCertificatesRequiresV2,
    generate_csr,
    generate_private_key,
)
from jinja2 import Environment, FileSystemLoader
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, EventBase, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, ModelError, WaitingStatus
from ops.pebble import Layer

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
CERTS_DIR_PATH = "/support/TLS"  # Certificate paths are hardcoded in AMF code
PRIVATE_KEY_NAME = "amf.key"
CSR_NAME = "amf.csr"
CERTIFICATE_NAME = "amf.pem"
CERTIFICATE_COMMON_NAME = "amf.sdcore"
CORE_NETWORK_FULL_NAME = "SDCORE5G"
CORE_NETWORK_SHORT_NAME = "SDCORE"
N2_RELATION_NAME = "fiveg-n2"


class AMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the SD-Core AMF operator."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            raise NotImplementedError("Scaling is not implemented for this charm")
        self._amf_container_name = self._amf_service_name = "amf"
        self._amf_container = self.unit.get_container(self._amf_container_name)
        self._nrf_requires = NRFRequires(charm=self, relation_name="fiveg-nrf")
        self.n2_provider = N2Provides(self, N2_RELATION_NAME)
        self._certificates = TLSCertificatesRequiresV2(self, "certificates")
        self._amf_metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}],
                }
            ],
        )
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
        self.framework.observe(self.on.config_changed, self._configure_amf)
        self.framework.observe(self.on.database_relation_joined, self._configure_amf)
        self.framework.observe(self._database.on.database_created, self._configure_amf)
        self.framework.observe(self.on.amf_pebble_ready, self._configure_amf)
        self.framework.observe(self._nrf_requires.on.nrf_available, self._configure_amf)
        self.framework.observe(self._nrf_requires.on.nrf_broken, self._on_nrf_broken)
        self.framework.observe(self.on.fiveg_nrf_relation_joined, self._configure_amf)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._on_n2_relation_joined)
        self.framework.observe(
            self.on.certificates_relation_created, self._on_certificates_relation_created
        )
        self.framework.observe(
            self.on.certificates_relation_joined, self._on_certificates_relation_joined
        )
        self.framework.observe(
            self.on.certificates_relation_broken, self._on_certificates_relation_broken
        )
        self.framework.observe(
            self._certificates.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self._certificates.on.certificate_expiring, self._on_certificate_expiring
        )

    def _configure_amf(self, event: EventBase) -> None:
        """Handle pebble ready event for AMF container.

        Args:
            event (PebbleReadyEvent, DatabaseCreatedEvent, NRFAvailableEvent): Juju event
        """
        if not self._amf_container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for service to start")
            event.defer()
            return
        if invalid_configs := self._get_invalid_configs():
            self.unit.status = BlockedStatus(
                f"The following configurations are not valid: {invalid_configs}"
            )
            return
        for relation in ["fiveg-nrf", "database"]:
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
        if not _get_pod_ip():
            self.unit.status = WaitingStatus("Waiting for pod IP address to be available")
            event.defer()
            return
        self._generate_config_file()
        self._configure_amf_workload()
        self._set_n2_information()
        self.unit.status = ActiveStatus()

    def _on_certificates_relation_created(self, event: EventBase) -> None:
        """Generates Private key."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        self._generate_private_key()

    def _on_certificates_relation_broken(self, event: EventBase) -> None:
        """Deletes TLS related artifacts and reconfigures AMF."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        self._delete_private_key()
        self._delete_csr()
        self._delete_certificate()
        self._configure_amf(event)

    def _on_certificates_relation_joined(self, event: EventBase) -> None:
        """Generates CSR and requests new certificate."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        if not self._private_key_is_stored():
            event.defer()
            return
        self._request_new_certificate()

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Pushes certificate to workload and configures AMF."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        if not self._csr_is_stored():
            logger.warning("Certificate is available but no CSR is stored")
            return
        if event.certificate_signing_request != self._get_stored_csr():
            logger.debug("Stored CSR doesn't match one in certificate available event")
            return
        self._store_certificate(event.certificate)
        self._configure_amf(event)

    def _on_certificate_expiring(self, event: CertificateExpiringEvent):
        """Requests new certificate."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        if event.certificate != self._get_stored_certificate():
            logger.debug("Expiring certificate is not the one stored")
            return
        self._request_new_certificate()

    def _on_nrf_broken(self, event: EventBase) -> None:
        """Event handler for NRF relation broken.

        Args:
            event (NRFBrokenEvent): Juju event
        """
        self.unit.status = BlockedStatus("Waiting for fiveg-nrf relation")

    def _generate_private_key(self) -> None:
        """Generates and stores private key."""
        private_key = generate_private_key()
        self._store_private_key(private_key)

    def _request_new_certificate(self) -> None:
        """Generates and stores CSR, and uses it to request a new certificate."""
        private_key = self._get_stored_private_key()
        csr = generate_csr(
            private_key=private_key,
            subject=CERTIFICATE_COMMON_NAME,
            sans_dns=[CERTIFICATE_COMMON_NAME],
        )
        self._store_csr(csr)
        self._certificates.request_certificate_creation(certificate_signing_request=csr)

    def _delete_private_key(self):
        """Removes private key from workload."""
        if not self._private_key_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
        logger.info("Removed private key from workload")

    def _delete_csr(self):
        """Deletes CSR from workload."""
        if not self._csr_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")
        logger.info("Removed CSR from workload")

    def _delete_certificate(self):
        """Deletes certificate from workload."""
        if not self._certificate_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
        logger.info("Removed certificate from workload")

    def _private_key_is_stored(self) -> bool:
        """Returns whether private key is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _csr_is_stored(self) -> bool:
        """Returns whether CSR is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")

    def _get_stored_certificate(self) -> str:
        """Returns stored certificate."""
        return str(self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read())

    def _get_stored_csr(self) -> str:
        """Returns stored CSR."""
        return str(self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{CSR_NAME}").read())

    def _get_stored_private_key(self) -> bytes:
        """Returns stored private key."""
        return str(
            self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read()
        ).encode()

    def _certificate_is_stored(self) -> bool:
        """Returns whether certificate is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _store_certificate(self, certificate: str) -> None:
        """Stores certificate in workload."""
        self._amf_container.push(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=certificate)
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: bytes) -> None:
        """Stores private key in workload."""
        self._amf_container.push(
            path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
            source=private_key.decode(),
        )
        logger.info("Pushed private key to workload")

    def _store_csr(self, csr: bytes) -> None:
        """Stores CSR in workload."""
        self._amf_container.push(path=f"{CERTS_DIR_PATH}/{CSR_NAME}", source=csr.decode().strip())
        logger.info("Pushed CSR to workload")

    def _get_invalid_configs(self) -> list[str]:
        """Returns list of invalid configurations.

        Returns:
            list: List of strings matching config keys.
        """
        invalid_configs = []
        if not self._get_dnn_config():
            invalid_configs.append("dnn")
        return invalid_configs

    def _get_dnn_config(self) -> Optional[str]:
        return self.model.config.get("dnn")

    def _on_n2_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handles N2 relation joined event.

        Args:
            event (RelationJoinedEvent): Juju event
        """
        self._set_n2_information()

    def _set_n2_information(self) -> None:
        """Sets N2 information for the N2 relation."""
        if not self._relation_created(N2_RELATION_NAME):
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
        if not (dnn := self._get_dnn_config()):
            raise ValueError("DNN configuration value is empty")
        content = self._render_config_file(
            ngapp_port=NGAPP_PORT,
            sctp_grpc_port=SCTP_GRPC_PORT,
            sbi_port=SBI_PORT,
            nrf_url=self._nrf_requires.nrf_url,
            amf_ip=_get_pod_ip(),  # type: ignore[arg-type]
            database_name=DATABASE_NAME,
            database_url=self._get_database_info()["uris"].split(",")[0],
            full_network_name=CORE_NETWORK_FULL_NAME,
            short_network_name=CORE_NETWORK_SHORT_NAME,
            dnn=dnn,
            scheme="https" if self._certificate_is_stored() else "http",
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
        dnn: str,
        scheme: str,
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
            dnn (str): Data Network name.
            scheme (str): SBI interface scheme ("http" or "https")

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
            dnn=dnn,
            scheme=scheme,
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
        return bool(self.model.relations.get(relation_name))

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
                        "command": f"/bin/amf --amfcfg {CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",  # noqa: E501
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


def _get_pod_ip() -> Optional[str]:
    """Returns the pod IP using juju client.

    Returns:
        str: The pod IP.
    """
    ip_address = check_output(["unit-get", "private-address"])
    return str(IPv4Address(ip_address.decode().strip())) if ip_address else None


if __name__ == "__main__":  # pragma: no cover
    main(AMFOperatorCharm)
