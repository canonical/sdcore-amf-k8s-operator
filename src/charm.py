#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SD-Core AMF service for K8s."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output
from typing import List, Optional, cast

import ops
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import (
    MetricsEndpointProvider,
)
from charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Provides
from charms.sdcore_nms_k8s.v0.sdcore_config import (
    SdcoreConfigRequires,
)
from charms.sdcore_nrf_k8s.v0.fiveg_nrf import NRFRequires
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    PrivateKey,
    TLSCertificatesRequiresV4,
)
from jinja2 import Environment, FileSystemLoader
from ops import (
    ActiveStatus,
    BlockedStatus,
    CollectStatusEvent,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
    main,
)
from ops.charm import (
    CharmBase,
    RelationBrokenEvent,
    RelationJoinedEvent,
    RemoveEvent,
)
from ops.framework import EventBase
from ops.pebble import Layer

from k8s_service import K8sService

logger = logging.getLogger(__name__)

PROMETHEUS_PORT = 9089
SBI_PORT = 29518
NGAPP_PORT = 38412
SCTP_GRPC_PORT = 9000
CONFIG_DIR_PATH = "/free5gc/config"
CONFIG_FILE_NAME = "amfcfg.conf"
CONFIG_TEMPLATE_DIR_PATH = "src/templates/"
CONFIG_TEMPLATE_NAME = "amfcfg.conf.j2"
WORKLOAD_VERSION_FILE_NAME = "/etc/workload-version"
CERTS_DIR_PATH = "/support/TLS"
PRIVATE_KEY_NAME = "amf.key"
CERTIFICATE_NAME = "amf.pem"
CERTIFICATE_COMMON_NAME = "amf.sdcore"
CORE_NETWORK_FULL_NAME = "SDCORE5G"
CORE_NETWORK_SHORT_NAME = "SDCORE"
N2_RELATION_NAME = "fiveg-n2"
LOGGING_RELATION_NAME = "logging"
FIVEG_NRF_RELATION_NAME = "fiveg_nrf"
SDCORE_CONFIG_RELATION_NAME = "sdcore_config"
TLS_RELATION_NAME = "certificates"
REPLICAS_RELATION_NAME = "replicas"


class AMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the SD-Core AMF operator for K8s."""

    def __init__(self, *args):
        super().__init__(*args)
        self.replicas = self.model.get_relation(REPLICAS_RELATION_NAME)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        self._amf_container_name = self._amf_service_name = "amf"
        self._amf_container = self.unit.get_container(self._amf_container_name)
        self._nrf_requires = NRFRequires(charm=self, relation_name=FIVEG_NRF_RELATION_NAME)
        self._webui_requires = SdcoreConfigRequires(
            charm=self, relation_name=SDCORE_CONFIG_RELATION_NAME
        )
        self.n2_provider = N2Provides(self, N2_RELATION_NAME)
        self._certificates = TLSCertificatesRequiresV4(
            charm=self,
            relationship_name=TLS_RELATION_NAME,
            certificate_requests=[self._get_certificate_request()],
        )
        self._amf_metrics_endpoint = MetricsEndpointProvider(
            self,
            refresh_event=[self.on.update_status],
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}],
                }
            ],
        )
        self.tracing = ops.tracing.Tracing(self, "tracing")
        self.unit.set_ports(PROMETHEUS_PORT, SBI_PORT, SCTP_GRPC_PORT)
        self._logging = LogForwarder(charm=self, relation_name=LOGGING_RELATION_NAME)
        self.k8s_service = K8sService(
            namespace=self.model.name,
            service_name=f"{self.app.name}-external",
            service_port=NGAPP_PORT,
            app_name=self.app.name,
            unit_id=self.unit.name.split("/")[-1],
        )
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.leader_elected, self._configure_amf)
        self.framework.observe(self.on.replicas_relation_changed, self._configure_amf)
        self.framework.observe(self.on.config_changed, self._configure_amf)
        self.framework.observe(self.on.update_status, self._configure_amf)
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
        if not self.unit.is_leader():
            logger.info("Unit `%s` is not leader", self.unit.name)
            if self._amf_service_is_running():
                logger.debug("Stopping `%s` service", self._amf_service_name)
                self._amf_container.stop(self._amf_service_name)
                logger.debug(
                    "Stopped service `%s` in non-leader unit", self._amf_service_name
                )
            return
        if self.replicas:
            self.replicas.data[self.app]["leader"] = self.unit.name
        if not self.k8s_service.is_created():
            self.k8s_service.create()
        if self.k8s_service.requires_patch():
            self.k8s_service.patch()
        if not self.ready_to_configure():
            logger.info("The preconditions for the configuration are not met yet.")
            return
        if not self._certificate_is_available():
            logger.info("The certificate is not available yet.")
            return
        certificate_update_required = self._check_and_update_certificate()
        desired_config_file = self._generate_amf_config_file()
        if config_update_required := self._is_config_update_required(desired_config_file):
            self._push_config_file(content=desired_config_file)
        should_restart = config_update_required or certificate_update_required
        self._configure_pebble(restart=should_restart)
        try:
            self._set_n2_information()
        except ValueError:
            return

    def _check_and_update_certificate(self) -> bool:
        """Check if the certificate or private key needs an update and perform the update.

        This method retrieves the currently assigned certificate and private key associated with
        the charm's TLS relation. It checks whether the certificate or private key has changed
        or needs to be updated. If an update is necessary, the new certificate or private key is
        stored.

        Returns:
            bool: True if either the certificate or the private key was updated, False otherwise.
        """
        provider_certificate, private_key = self._certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request()
        )
        if not provider_certificate or not private_key:
            logger.debug("Certificate or private key is not available")
            return False
        if certificate_update_required := self._is_certificate_update_required(
            provider_certificate.certificate
        ):
            self._store_certificate(certificate=provider_certificate.certificate)
        if private_key_update_required := self._is_private_key_update_required(private_key):
            self._store_private_key(private_key=private_key)
        return certificate_update_required or private_key_update_required

    def _on_collect_unit_status(self, event: CollectStatusEvent):  # noqa C901
        """Check the unit status and set to Unit when CollectStatusEvent is fired.

        Args:
            event: CollectStatusEvent
        """
        if not self.unit.is_leader():
            event.add_status(ActiveStatus("standby (non-leader)"))
            logger.info("Unit in standby (non-leader)")
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

        if not self._get_n2_amf_ip() or not self._get_n2_amf_hostname():
            event.add_status(BlockedStatus("Waiting for MetalLB to be enabled"))
            logger.info("Waiting for MetalLB to be enabled")
            return

        if not self._certificate_is_available():
            event.add_status(WaitingStatus("Waiting for certificates to be available"))
            logger.info("Waiting for certificates to be available")
            return

        if not self._amf_service_is_running():
            event.add_status(WaitingStatus("Waiting for AMF service to start"))
            logger.info("Waiting for AMF service to start")
            return

        event.add_status(ActiveStatus())

    def _get_certificate_request(self) -> CertificateRequestAttributes:
        return CertificateRequestAttributes(
            common_name=CERTIFICATE_COMMON_NAME,
            sans_dns=frozenset([CERTIFICATE_COMMON_NAME]),
        )

    def _missing_relations(self) -> List[str]:
        """Return list of missing relations.

        If all the relations are created, it returns an empty list.

        Returns:
            list: missing relation names.
        """
        missing_relations = []
        for relation in [
            FIVEG_NRF_RELATION_NAME,
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
        # is removed.
        #
        # We only remove the service if the leader is removed. This is presumed
        # to be the only healthy unit, and therefore the last remaining one when
        # removed (since all other units will block if they are not leader)
        #
        # This is a best effort removal of the service. There are edge cases
        # where the leader status is removed from the leader unit before all
        # hooks have finished running. In this case, we will leave behind a
        # dirty state in k8s, but it will be cleaned up when the juju model is
        # destroyed. It will be reused if the charm is re-deployed.
        if self.unit.is_leader():
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

    def _is_certificate_update_required(self, certificate: Certificate) -> bool:
        return self._get_existing_certificate() != certificate

    def _is_private_key_update_required(self, private_key: PrivateKey) -> bool:
        return self._get_existing_private_key() != private_key

    def _get_existing_certificate(self) -> Optional[Certificate]:
        return self._get_stored_certificate() if self._certificate_is_stored() else None

    def _get_existing_private_key(self) -> Optional[PrivateKey]:
        return self._get_stored_private_key() if self._private_key_is_stored() else None

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
        self._delete_certificate()
        self._delete_private_key()

    def _certificate_is_available(self) -> bool:
        cert, key = self._certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request()
        )
        return bool(cert and key)

    def _delete_certificate(self):
        """Delete certificate from workload."""
        if self._certificate_is_stored():
            self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
            logger.info("Removed certificate from workload")

    def _delete_private_key(self):
        """Delete private key from workload."""
        if self._private_key_is_stored():
            self._amf_container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
            logger.info("Removed private key from workload")

    def _get_stored_certificate(self) -> Certificate:
        cert_string = str(
            self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read()
        )
        return Certificate.from_string(cert_string)

    def _get_stored_private_key(self) -> PrivateKey:
        key_string = str(
            self._amf_container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read()
        )
        return PrivateKey.from_string(key_string)

    def _certificate_is_stored(self) -> bool:
        """Return whether certificate is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _private_key_is_stored(self) -> bool:
        """Return whether private key is stored in workload."""
        return self._amf_container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _store_certificate(self, certificate: Certificate) -> None:
        """Store certificate in workload."""
        self._amf_container.push(
            path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=str(certificate)
        )
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: PrivateKey) -> None:
        """Store private key in workload."""
        self._amf_container.push(
            path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
            source=str(private_key),
        )
        logger.info("Pushed private key to workload")

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
        if not self._is_log_level_valid():
            invalid_configs.append("log-level")
        return invalid_configs

    def _get_dnn_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("dnn"))

    def _get_log_level_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("log-level"))

    def _is_log_level_valid(self) -> bool:
        log_level = self._get_log_level_config()
        return log_level in ["debug", "info", "warn", "error", "fatal", "panic"]

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
        n2_amf_ip = self._get_n2_amf_ip()
        n2_amf_hostname = self._get_n2_amf_hostname()
        if not n2_amf_ip or not n2_amf_hostname:
            return
        self.n2_provider.set_n2_information(
            amf_ip_address=n2_amf_ip,
            amf_hostname=n2_amf_hostname,
            amf_port=NGAPP_PORT,
        )

    def _generate_amf_config_file(self) -> str:
        """Handle creation of the AMF config file based on a given template.

        Returns:
            content (str): desired config file content
        """
        if not (dnn := self._get_dnn_config()):
            raise ValueError("DNN configuration value is empty")
        if not (pod_ip := _get_pod_ip()):
            raise ValueError("Pod IP is not available")
        if not self._nrf_requires.nrf_url:
            raise ValueError("NRF URL is not available")
        if not self._webui_requires.webui_url:
            raise ValueError("Webui URL is not available")
        if not (log_level := self._get_log_level_config()):
            raise ValueError("Log level configuration value is empty")

        return self._render_config_file(
            ngapp_port=NGAPP_PORT,
            sctp_grpc_port=SCTP_GRPC_PORT,
            sbi_port=SBI_PORT,
            nrf_url=self._nrf_requires.nrf_url,
            amf_ip=pod_ip,
            full_network_name=CORE_NETWORK_FULL_NAME,
            short_network_name=CORE_NETWORK_SHORT_NAME,
            dnn=dnn,
            scheme="https",
            webui_uri=self._webui_requires.webui_url,
            log_level=log_level,
            tls_pem=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}",
            tls_key=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
        )

    @staticmethod
    def _render_config_file(
        *,
        amf_ip: str,
        ngapp_port: int,
        sctp_grpc_port: int,
        sbi_port: int,
        nrf_url: str,
        full_network_name: str,
        short_network_name: str,
        dnn: str,
        scheme: str,
        webui_uri: str,
        log_level: str,
        tls_pem: str,
        tls_key: str,
    ) -> str:
        """Render the AMF config file.

        Args:
            amf_ip (str): IP address of the AMF.
            ngapp_port (int): AMF NGAP port.
            sctp_grpc_port (int): AMF SCTP port.
            sbi_port (int): AMF SBi port.
            nrf_url (str): URL of the NRF.
            full_network_name (str): Full name of the network.
            short_network_name (str): Short name of the network.
            dnn (str): Data Network name.
            scheme (str): SBI interface scheme ("http" or "https")
            webui_uri (str) : URL of the Webui.
            log_level (str): Log level for the AMF.
            tls_pem (str): TLS certificate file.
            tls_key (str): TLS key file.

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
            full_network_name=full_network_name,
            short_network_name=short_network_name,
            dnn=dnn,
            scheme=scheme,
            webui_uri=webui_uri,
            log_level=log_level,
            tls_pem=tls_pem,
            tls_key=tls_key,
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
                        "command": f"/bin/amf --cfg {CONFIG_DIR_PATH}/{CONFIG_FILE_NAME}",
                        "environment": self._amf_environment_variables,
                    },
                },
            }
        )

    @property
    def _amf_environment_variables(self) -> dict:
        """Return environment variables for the amf container.

        Returns:
            dict: Environment variables.
        """
        return {
            "GOTRACEBACK": "crash",
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
            logger.debug("Cannot connect to AMF container")
            return False
        try:
            service = self._amf_container.get_service(self._amf_service_name)
        except ModelError:
            logger.debug("Service AMF not found")
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
