#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SD-Core AMF service for K8s."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output
from typing import List, Optional, cast

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires  # type: ignore[import]
from charms.loki_k8s.v1.loki_push_api import LogForwarder  # type: ignore[import]
from charms.prometheus_k8s.v0.prometheus_scrape import (  # type: ignore[import]
    MetricsEndpointProvider,
)
from charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Provides  # type: ignore[import]
from charms.sdcore_nrf_k8s.v0.fiveg_nrf import NRFRequires  # type: ignore[import]
from charms.sdcore_webui_k8s.v0.sdcore_config import (  # type: ignore[import]
    SdcoreConfigRequires,
)
from charms.tls_certificates_interface.v3.tls_certificates import (  # type: ignore[import]
    CertificateExpiringEvent,
    TLSCertificatesRequiresV3,
    generate_csr,
    generate_private_key,
)
from jinja2 import Environment, FileSystemLoader
from k8s_service import K8sService
from ops import (
    ActiveStatus,
    BlockedStatus,
    CollectStatusEvent,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)
from ops.charm import (
    CharmBase,
    EventBase,
    RelationBrokenEvent,
    RelationJoinedEvent,
    RemoveEvent,
)
from ops.main import main
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
WORKLOAD_VERSION_FILE_NAME = "/etc/workload-version"
CERTS_DIR_PATH = "/support/TLS"  # Certificate paths are hardcoded in AMF code
PRIVATE_KEY_NAME = "amf.key"
CSR_NAME = "amf.csr"
CERTIFICATE_NAME = "amf.pem"
CERTIFICATE_COMMON_NAME = "amf.sdcore"
CORE_NETWORK_FULL_NAME = "SDCORE5G"
CORE_NETWORK_SHORT_NAME = "SDCORE"
N2_RELATION_NAME = "fiveg-n2"
LOGGING_RELATION_NAME = "logging"
FIVEG_NRF_RELATION_NAME = "fiveg_nrf"
SDCORE_CONFIG_RELATION_NAME = "sdcore_config"
TLS_RELATION_NAME = "certificates"
DATABASE_RELATION_NAME = "database"


class AMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the SD-Core AMF operator for K8s."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        if not self.unit.is_leader():
            # NOTE: In cases where leader status is lost before the charm is
            # finished processing all teardown events, this prevents teardown
            # event code from running. Luckily, for this charm, none of the
            # teardown code is necessary to perform if we're removing the
            # charm.
            return
        self._amf_container_name = self._amf_service_name = "amf"
        self._amf_container = self.unit.get_container(self._amf_container_name)
        self._nrf_requires = NRFRequires(charm=self, relation_name=FIVEG_NRF_RELATION_NAME)
        self._webui_requires = SdcoreConfigRequires(
            charm=self, relation_name=SDCORE_CONFIG_RELATION_NAME
        )
        self.n2_provider = N2Provides(self, N2_RELATION_NAME)
        self._certificates = TLSCertificatesRequiresV3(self, TLS_RELATION_NAME)
        self._amf_metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}],
                }
            ],
        )
        self.unit.set_ports(PROMETHEUS_PORT, SBI_PORT, SCTP_GRPC_PORT)
        self._database = DatabaseRequires(
            self, relation_name=DATABASE_RELATION_NAME, database_name=DATABASE_NAME
        )
        self._logging = LogForwarder(charm=self, relation_name=LOGGING_RELATION_NAME)
        self.k8s_service = K8sService(
            namespace=self.model.name,
            service_name=f"{self.app.name}-external",
            service_port=NGAPP_PORT,
            app_name=self.app.name,
        )
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.config_changed, self._configure_amf)
        self.framework.observe(self.on.update_status, self._configure_amf)
        self.framework.observe(self.on.database_relation_joined, self._configure_amf)
        self.framework.observe(self._database.on.database_created, self._configure_amf)
        self.framework.observe(self.on.amf_pebble_ready, self._configure_amf)
        self.framework.observe(self._nrf_requires.on.nrf_available, self._configure_amf)
        self.framework.observe(self.on.fiveg_nrf_relation_joined, self._configure_amf)
        self.framework.observe(self._webui_requires.on.webui_url_available, self._configure_amf)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._on_n2_relation_joined)
        self.framework.observe(self.on.certificates_relation_joined, self._configure_amf)
        self.framework.observe(self.on.sdcore_config_relation_joined, self._configure_amf)
        self.framework.observe(
            self.on.certificates_relation_broken, self._on_certificates_relation_broken
        )
        self.framework.observe(self._certificates.on.certificate_available, self._configure_amf)
        self.framework.observe(
            self._certificates.on.certificate_expiring, self._on_certificate_expiring
        )

    def _configure_amf(self, _: EventBase) -> None:
        """Handle Juju events.

        This event handler is called for every event that affects the charm state
        (ex. configuration files, relation data). This method performs a couple of checks
        to make sure that the workload is ready to be started. Then, it configures the AMF
        workload, runs the Pebble services and expose the service information through
        charm's interface.

        Args:
            _ (EventBase): Juju event
        """
        if not self.k8s_service.is_created():
            self.k8s_service.create()

        if not self.ready_to_configure():
            logger.info("The preconditions for the configuration are not met yet.")
            return

        if not self._private_key_is_stored():
            self._generate_private_key()

        if not self._csr_is_stored():
            self._request_new_certificate()

        provider_certificate = self._get_current_provider_certificate()
        if not provider_certificate:
            return

        if certificate_update_required := self._is_certificate_update_required(
            provider_certificate
        ):
            self._store_certificate(certificate=provider_certificate)

        desired_config_file = self._generate_amf_config_file()
        if config_update_required := self._is_config_update_required(desired_config_file):
            self._push_config_file(content=desired_config_file)

        should_restart = config_update_required or certificate_update_required
        self._configure_pebble(restart=should_restart)

        try:
            self._set_n2_information()
        except ValueError:
            return

    def _on_collect_unit_status(self, event: CollectStatusEvent):  # noqa C901
        """Check the unit status and set to Unit when CollectStatusEvent is fired.

        Args:
            event: CollectStatusEvent
        """
        if not self.unit.is_leader():
            # NOTE: In cases where leader status is lost before the charm is
            # finished processing all teardown events, this prevents teardown
            # event code from running. Luckily, for this charm, none of the
            # teardown code is necessary to perform if we're removing the
            # charm.
            event.add_status(BlockedStatus("Scaling is not implemented for this charm"))
            logger.info("Scaling is not implemented for this charm")
            return

        if not self._amf_container.can_connect():
            event.add_status(MaintenanceStatus("Waiting for service to start"))
            logger.info("Waiting for service to start")
            return

        if invalid_configs := self._get_invalid_configs():
            event.add_status(
                BlockedStatus(f"The following configurations are not valid: {invalid_configs}")
            )
            logger.info("The following configurations are not valid: %s", invalid_configs)
            return

        if version := self._get_workload_version():
            self.unit.set_workload_version(version)

        if missing_relations := self._missing_relations():
            event.add_status(
                BlockedStatus(f"Waiting for {', '.join(missing_relations)} relation(s)")
            )
            logger.info("Waiting for %s  relation(s)", ", ".join(missing_relations))
            return

        if not self._database_is_available():
            event.add_status(WaitingStatus("Waiting for the amf database to be available"))
            logger.info("Waiting for the amf database to be available")
            return

        if not self._get_database_info():
            event.add_status(WaitingStatus("Waiting for AMF database info to be available"))
            logger.info("Waiting for AMF database info to be available")
            return

        if not self._nrf_requires.nrf_url:
            event.add_status(WaitingStatus("Waiting for NRF data to be available"))
            logger.info("Waiting for NRF data to be available")
            return

        if not self._webui_requires.webui_url:
            event.add_status(WaitingStatus("Waiting for Webui data to be available"))
            logger.info("Waiting for Webui data to be available")
            return

        if not self._amf_container.exists(path=CONFIG_DIR_PATH):
            event.add_status(WaitingStatus("Waiting for storage to be attached"))
            logger.info("Waiting for storage to be attached")
            return

        if not _get_pod_ip():
            event.add_status(WaitingStatus("Waiting for pod IP address to be available"))
            logger.info("Waiting for pod IP address to be available")
            return

        try:
            self._set_n2_information()
        except ValueError:
            event.add_status(BlockedStatus("Waiting for MetalLB to be enabled"))
            logger.info("Waiting for MetalLB to be enabled")

        if self._csr_is_stored() and not self._get_current_provider_certificate():
            event.add_status(WaitingStatus("Waiting for certificates to be stored"))
            logger.info("Waiting for certificates to be stored")
            return

        if not self._amf_service_is_running():
            event.add_status(WaitingStatus("Waiting for AMF service to start"))
            logger.info("Waiting for AMF service to start")
            return

        event.add_status(ActiveStatus())

    def _missing_relations(self) -> List[str]:
        """Return list of missing relations.

        If all the relations are created, it returns an empty list.

        Returns:
            list: missing relation names.
        """
        missing_relations = []
        for relation in [
            FIVEG_NRF_RELATION_NAME,
            DATABASE_RELATION_NAME,
            TLS_RELATION_NAME,
            SDCORE_CONFIG_RELATION_NAME,
        ]:
            if not self._relation_created(relation):
                missing_relations.append(relation)
        return missing_relations

    def ready_to_configure(self) -> bool:
        """Return whether the preconditions are met to proceed with the configuration.

        Returns:
            ready_to_configure: True if all conditions are met else False
        """
        if not self._amf_container.can_connect():
            return False

        if self._get_invalid_configs():
            return False

        if self._missing_relations():
            return False

        if not self._database_is_available():
            return False

        if not self._get_database_info():
            return False

        if not self._nrf_requires.nrf_url:
            return False

        if not self._webui_requires.webui_url:
            return False

        if not self._amf_container.exists(path=CONFIG_DIR_PATH):
            return False

        if not _get_pod_ip():
            return False

        return True

    def _on_remove(self, event: RemoveEvent) -> None:
        # NOTE: We want to perform this removal only if the last remaining unit
        # is removed. This charm does not support scaling, so it *should* be
        # the only unit.
        #
        # However, to account for the case where the charm was scaled up, and
        # now needs to be scaled back down, we only remove the service if the
        # leader is removed. This is presumed to be the only healthy unit, and
        # therefore the last remaining one when removed (since all other units
        # will block if they are not leader)
        #
        # This is a best effort removal of the service. There are edge cases
        # where the leader status is removed from the leader unit before all
        # hooks are finished running. In this case, we will leave behind a
        # dirty state in k8s, but it will be cleaned up when the juju model is
        # destroyed. It will be re-used if the charm is re-deployed.
        if self.k8s_service.is_created():
            self.k8s_service.remove()

    def _is_config_update_required(self, content: str) -> bool:
        """Decide whether config update is required by checking existence and config content.

        Args:
            content (str): desired config file content

        Returns:
            True if config update is required else False
        """
        if not self._config_file_is_written() or not self._config_file_content_matches(
            content=content
        ):
            return True
        return False

    def _config_file_is_written(self) -> bool:
        """Return whether the config file was written to the workload container.

        Returns:
            bool: Whether the config file was written.
        """
        return bool(self._amf_container.exists(f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}"))

    def _is_certificate_update_required(self, provider_certificate) -> bool:
        """Check the provided certificate and existing certificate.

        Return True if update is required.

        Args:
            provider_certificate: str
        Returns:
            True if update is required else False
        """
        return self._get_existing_certificate() != provider_certificate

    def _get_existing_certificate(self) -> str:
        """Return the existing certificate if present else empty string."""
        return self._get_stored_certificate() if self._certificate_is_stored() else ""

    def _configure_pebble(self, restart=False) -> None:
        """Configure the Pebble layer.

        Args:
            restart (bool): Whether to restart the AMF container.
        """
        plan = self._amf_container.get_plan()
        if plan.services != self._amf_pebble_layer.services:
            self._amf_container.add_layer(
                self._amf_container_name, self._amf_pebble_layer, combine=True
            )
            self._amf_container.replan()
            logger.info("New layer added: %s", self._amf_pebble_layer)
        if restart:
            self._amf_container.restart(self._amf_service_name)
            logger.info("Restarted container %s", self._amf_service_name)
            return
        self._amf_container.replan()

    def _on_certificates_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Delete TLS related artifacts and reconfigures AMF."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        self._delete_private_key()
        self._delete_csr()
        self._delete_certificate()

    def _on_certificate_expiring(self, event: CertificateExpiringEvent):
        """Request new certificate."""
        if not self._amf_container.can_connect():
            event.defer()
            return
        if event.certificate != self._get_stored_certificate():
            logger.debug("Expiring certificate is not the one stored")
            return
        self._request_new_certificate()

    def _get_current_provider_certificate(self) -> str | None:
        """Compare the current certificate request to what is in the interface.

        Returns The current valid provider certificate if present
        """
        csr = self._get_stored_csr()
        for provider_certificate in self._certificates.get_assigned_certificates():
            if provider_certificate.csr == csr:
                return provider_certificate.certificate
        return None

    def _update_certificate(self, provider_certificate) -> bool:
        """Compare the provided certificate to what is stored.

        Returns True if the certificate was updated
        """
        existing_certificate = (
            self._get_stored_certificate() if self._certificate_is_stored() else ""
        )

        if not existing_certificate == provider_certificate:
            self._store_certificate(certificate=provider_certificate)
            return True
        return False

    def _generate_private_key(self) -> None:
        """Generate and stores private key."""
        private_key = generate_private_key()
        self._store_private_key(private_key)

    def _request_new_certificate(self) -> None:
        """Generate and stores CSR, and uses it to request a new certificate."""
        private_key = self._get_stored_private_key()
        csr = generate_csr(
            private_key=private_key,
            subject=CERTIFICATE_COMMON_NAME,
            sans_dns=[CERTIFICATE_COMMON_NAME],
        )
        self._store_csr(csr)
        self._certificates.request_certificate_creation(certificate_signing_request=csr)

    def _delete_private_key(self):
        """Remove private key from workload."""
        if not self._private_key_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
        logger.info("Removed private key from workload")

    def _delete_csr(self):
        """Delete CSR from workload."""
        if not self._csr_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")
        logger.info("Removed CSR from workload")

    def _delete_certificate(self):
        """Delete certificate from workload."""
        if not self._certificate_is_stored():
            return
        self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
        logger.info("Removed certificate from workload")

    def _private_key_is_stored(self) -> bool:
        """Return whether private key is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _csr_is_stored(self) -> bool:
        """Return whether CSR is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")

    def _get_stored_certificate(self) -> str:
        """Return stored certificate."""
        return str(self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read())

    def _get_stored_csr(self) -> str:
        """Return stored CSR."""
        return self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{CSR_NAME}").read()

    def _get_stored_private_key(self) -> bytes:
        """Return stored private key."""
        return str(
            self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read()
        ).encode()

    def _certificate_is_stored(self) -> bool:
        """Return whether certificate is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _store_certificate(self, certificate: str) -> None:
        """Store certificate in workload."""
        self._amf_container.push(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=certificate)
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: bytes) -> None:
        """Store private key in workload."""
        self._amf_container.push(
            path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
            source=private_key.decode(),
        )
        logger.info("Pushed private key to workload")

    def _store_csr(self, csr: bytes) -> None:
        """Store CSR in workload."""
        self._amf_container.push(path=f"{CERTS_DIR_PATH}/{CSR_NAME}", source=csr.decode().strip())
        logger.info("Pushed CSR to workload")

    def _get_workload_version(self) -> str:
        """Return the workload version.

        Checks for the presence of /etc/workload-version file
        and if present, returns the contents of that file. If
        the file is not present, an empty string is returned.

        Returns:
            string: A human readable string representing the
            version of the workload
        """
        if self._amf_container.exists(path=f"{WORKLOAD_VERSION_FILE_NAME}"):
            version_file_content = self._amf_container.pull(
                path=f"{WORKLOAD_VERSION_FILE_NAME}"
            ).read()
            return version_file_content
        return ""

    def _get_invalid_configs(self) -> list[str]:
        """Return list of invalid configurations.

        Returns:
            list: List of strings matching config keys.
        """
        invalid_configs = []
        if not self._get_dnn_config():
            invalid_configs.append("dnn")
        return invalid_configs

    def _get_dnn_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("dnn"))

    def _get_external_amf_ip_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("external-amf-ip"))

    def _get_external_amf_hostname_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("external-amf-hostname"))

    def _on_n2_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle N2 relation joined event.

        Args:
            event (RelationJoinedEvent): Juju event
        """
        try:
            self._set_n2_information()
        except ValueError:
            return

    def _get_n2_amf_ip(self) -> Optional[str]:
        """Return the IP to send for the N2 interface.

        If a configuration is provided, it is returned, otherwise
        returns the IP of the external LoadBalancer Service.

        Returns:
            str/None: IP address of the AMF if available else None
        """
        if configured_ip := self._get_external_amf_ip_config():
            return configured_ip
        return self.k8s_service.get_ip()

    def _get_n2_amf_hostname(self) -> str:
        """Return the hostname to send for the N2 interface.

        If a configuration is provided, it is returned. If that is
        not available, returns the hostname of the external LoadBalancer
        Service. If the LoadBalancer Service does not have a hostname,
        returns the internal Kubernetes service FQDN.

        Returns:
            str: Hostname of the AMF
        """
        if configured_hostname := self._get_external_amf_hostname_config():
            return configured_hostname
        elif lb_hostname := self.k8s_service.get_hostname():
            return lb_hostname
        return self._amf_hostname()

    def _set_n2_information(self) -> None:
        """Set N2 information for the N2 relation."""
        if not self._relation_created(N2_RELATION_NAME):
            return
        if not self._amf_service_is_running():
            return
        self.n2_provider.set_n2_information(
            amf_ip_address=self._get_n2_amf_ip(),
            amf_hostname=self._get_n2_amf_hostname(),
            amf_port=NGAPP_PORT,
        )

    def _generate_amf_config_file(self) -> str:
        """Handle creation of the AMF config file based on a given template.

        Returns:
            content (str): desired config file content
        """
        if not (dnn := self._get_dnn_config()):
            raise ValueError("DNN configuration value is empty")

        return self._render_config_file(
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
            scheme="https",
            webui_uri=self._webui_requires.webui_url,
        )

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
        webui_uri: str,
    ) -> str:
        """Render the AMF config file.

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
            webui_uri (str) : URL of the Webui.

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
            webui_uri=webui_uri,
        )
        return content

    def _push_config_file(self, content: str) -> None:
        """Write the AMF config file and pushes it to the container.

        Args:
            content (str): Content of the config file.
        """
        self._amf_container.push(
            path=f"{CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",
            source=content,
        )
        logger.info("Pushed %s config file", CONFIG_FILE_NAME)

    def _relation_created(self, relation_name: str) -> bool:
        """Return True if the relation is created, False otherwise.

        Args:
            relation_name (str): Name of the relation.

        Returns:
            bool: True if the relation is created, False otherwise.
        """
        return bool(self.model.relations.get(relation_name))

    def _config_file_content_matches(self, content: str) -> bool:
        """Return whether the amfcfg config file content matches the provided content.

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
        """Return pebble layer for the amf container.

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
        """Return the database data.

        Returns:
            Dict: The database data.
        """
        if not self._database_is_available():
            raise RuntimeError(f"Database `{DATABASE_NAME}` is not available")
        return self._database.fetch_relation_data()[self._database.relations[0].id]

    def _database_is_available(self) -> bool:
        """Return True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._database.is_resource_created()

    @property
    def _amf_environment_variables(self) -> dict:
        """Return environment variables for the amf container.

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
        """Build and returns the AMF hostname in the cluster.

        Returns:
            str: The AMF hostname.
        """
        return f"{self.model.app.name}-external.{self.model.name}.svc.cluster.local"

    def _amf_service_is_running(self) -> bool:
        """Return whether the AMF service is running.

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
    """Return the pod IP using juju client.

    Returns:
        str: The pod IP.
    """
    ip_address = check_output(["unit-get", "private-address"])
    return str(IPv4Address(ip_address.decode().strip())) if ip_address else None


if __name__ == "__main__":  # pragma: no cover
    main(AMFOperatorCharm)
