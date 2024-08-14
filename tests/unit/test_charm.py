# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import os
from typing import Any, Generator
from unittest.mock import Mock, PropertyMock, patch

import pytest
from charm import AMFOperatorCharm
from k8s_service import K8sService
from ops import ActiveStatus, BlockedStatus, WaitingStatus, testing

from lib.charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateSigningRequest,
    PrivateKey,
    ProviderCertificate,
)
from tests.unit.certificates_helpers import (
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)

CONTAINER_NAME = "amf"
DB_APPLICATION_NAME = "mongodb-k8s"
DB_RELATION_NAME = "database"
NRF_APPLICATION_NAME = "nrf"
NRF_RELATION_NAME = "fiveg_nrf"
NRF_URL = "http://nrf:8081"
WEBUI_URL = "sdcore-webui:9876"
SDCORE_CONFIG_RELATION_NAME = "sdcore_config"
NMS_APPLICATION_NAME = "sdcore-nms-operator"
TLS_APPLICATION_NAME = "tls-certificates-operator"
TLS_RELATION_NAME = "certificates"
NAMESPACE = "whatever"


class TestCharm:
    patcher_check_output = patch("charm.check_output")
    patcher_k8s_service = patch("charm.K8sService", autospec=K8sService)
    patcher_nrf_url = patch(
        "charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock
    )
    patcher_webui_url = patch(
        "charms.sdcore_nms_k8s.v0.sdcore_config.SdcoreConfigRequires.webui_url",
        new_callable=PropertyMock,
    )
    patcher_is_resource_created = patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created"
    )
    patcher_get_assigned_certificate = patch(
        "charms.tls_certificates_interface.v4.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate"
    )

    @pytest.fixture()
    def setup(self):
        self.mock_get_assigned_certificate = TestCharm.patcher_get_assigned_certificate.start()
        self.mock_is_resource_created = TestCharm.patcher_is_resource_created.start()
        self.mock_nrf_url = TestCharm.patcher_nrf_url.start()
        self.mock_webui_url = TestCharm.patcher_webui_url.start()
        self.mock_check_output = TestCharm.patcher_check_output.start()
        self.mock_k8s_service = TestCharm.patcher_k8s_service.start().return_value

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def setup_harness(self, setup, request):
        self.harness = testing.Harness(AMFOperatorCharm)
        self.harness.set_model_name(name=NAMESPACE)
        self.harness.set_leader(is_leader=True)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.teardown)

    @pytest.fixture()
    def database_relation_id(self) -> Generator[int, Any, Any]:
        database_relation_id = self.harness.add_relation(DB_RELATION_NAME, DB_APPLICATION_NAME)
        self.harness.add_relation_unit(
            relation_id=database_relation_id, remote_unit_name=f"{DB_APPLICATION_NAME}/0"
        )
        self.harness.update_relation_data(
            relation_id=database_relation_id,
            app_or_unit=DB_APPLICATION_NAME,
            key_values={
                "username": "dummy",
                "password": "dummy",
                "uris": "http://dummy",
            },
        )
        yield database_relation_id

    @pytest.fixture()
    def nrf_relation_id(self) -> Generator[int, Any, Any]:
        yield self.harness.add_relation(
            relation_name=NRF_RELATION_NAME,
            remote_app=DB_APPLICATION_NAME,
        )

    @pytest.fixture()
    def certificates_relation_id(self) -> Generator[int, Any, Any]:
        yield self.harness.add_relation(
            relation_name=TLS_RELATION_NAME,
            remote_app=TLS_APPLICATION_NAME,
        )

    @pytest.fixture()
    def sdcore_config_relation_id(self) -> Generator[int, Any, Any]:
        sdcore_config_relation_id = self.harness.add_relation(
            relation_name=SDCORE_CONFIG_RELATION_NAME,
            remote_app=NMS_APPLICATION_NAME,
        )
        self.harness.add_relation_unit(
            relation_id=sdcore_config_relation_id, remote_unit_name=f"{NMS_APPLICATION_NAME}/0"
        )
        self.harness.update_relation_data(
            relation_id=sdcore_config_relation_id,
            app_or_unit=NMS_APPLICATION_NAME,
            key_values={
                "webui_url": WEBUI_URL,
            },
        )
        yield sdcore_config_relation_id

    @staticmethod
    def _read_file(path: str) -> str:
        """Read a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content

    def example_cert_and_key(self, tls_relation_id: int) -> tuple[ProviderCertificate, PrivateKey]:
        private_key_str = generate_private_key()
        csr = generate_csr(
            private_key=private_key_str,
            common_name="amf",
        )
        ca_private_key = generate_private_key()
        ca_certificate = generate_ca(
            private_key=ca_private_key,
            common_name="ca.com",
            validity=365,
        )
        certificate_str = generate_certificate(
            csr=csr,
            ca=ca_certificate,
            ca_key=ca_private_key,
            validity=365,
        )
        provider_certificate = ProviderCertificate(
            relation_id=tls_relation_id,
            certificate=Certificate.from_string(certificate_str),
            certificate_signing_request=CertificateSigningRequest.from_string(csr),
            ca=Certificate.from_string(ca_certificate),
            chain=[Certificate.from_string(ca_certificate)],
        )
        private_key = PrivateKey.from_string(private_key_str)
        return provider_certificate, private_key

    def test_given_fiveg_nrf_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, certificates_relation_id, sdcore_config_relation_id, database_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus("Waiting for fiveg_nrf relation(s)")

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, nrf_relation_id, sdcore_config_relation_id, certificates_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus("Waiting for database relation(s)")

    def test_given_certificates_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, nrf_relation_id, sdcore_config_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.add_relation(relation_name=DB_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for certificates relation(s)"
        )

    def test_given_sdcore_config_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, nrf_relation_id, certificates_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.add_relation(relation_name=DB_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for sdcore_config relation(s)"
        )

    def test_given_amf_charm_in_active_state_when_nrf_relation_breaks_then_status_is_blocked(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.harness.remove_relation(nrf_relation_id)
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus("Waiting for fiveg_nrf relation(s)")

    def test_given_amf_charm_in_active_state_when_database_relation_breaks_then_status_is_blocked(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.harness.remove_relation(database_relation_id)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus("Waiting for database relation(s)")

    def test_given_amf_charm_in_active_state_when_sdcore_config_relation_breaks_then_status_is_blocked(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.harness.remove_relation(sdcore_config_relation_id)
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for sdcore_config relation(s)"
        )

    def test_given_relations_created_and_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self, nrf_relation_id, certificates_relation_id, sdcore_config_relation_id
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.add_relation(relation_name=DB_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.mock_is_resource_created.return_value = False
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for the amf database to be available"
        )

    def test_given_database_info_not_available_when_pebble_ready_then_status_is_waiting(
        self, nrf_relation_id, certificates_relation_id, sdcore_config_relation_id
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_is_resource_created.return_value = True
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.add_relation(relation_name=DB_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for AMF database info to be available"
        )

    def test_given_nrf_data_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = ""
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for NRF data to be available"
        )

    def test_given_webui_data_not_available_when_pebble_ready_then_status_is_waiting(
        self, database_relation_id, nrf_relation_id, certificates_relation_id
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.add_relation(
            relation_name=SDCORE_CONFIG_RELATION_NAME,
            remote_app=NMS_APPLICATION_NAME,
        )
        self.mock_webui_url.return_value = ""
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for Webui data to be available"
        )

    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for storage to be attached"
        )

    def test_given_certificates_not_stored_when_pebble_ready_then_status_is_waiting(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_get_assigned_certificate.return_value = None, None
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus(
            "Waiting for certificates to be available"
        )

    def test_given_relations_created_and_database_available_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_check_output.return_value = b"1.1.1.1"
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_webui_url.return_value = WEBUI_URL
        root = self.harness.get_filesystem_root(CONTAINER_NAME)

        self.harness.container_pebble_ready(CONTAINER_NAME)
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
        assert (root / "support/TLS/amf.key").read_text() == str(private_key)
        assert (root / "support/TLS/amf.pem").read_text() == str(provider_certificate.certificate)
        assert (root / "free5gc/config/amfcfg.conf").read_text() == expected_content.strip()

    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        config_modification_time = (root / "free5gc/config/amfcfg.conf").stat().st_mtime
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_webui_url.return_value = WEBUI_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        assert (root / "free5gc/config/amfcfg.conf").stat().st_mtime == config_modification_time

    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)

        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )

        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        expected_plan = {
            "services": {
                CONTAINER_NAME: {
                    "startup": "enabled",
                    "override": "replace",
                    "command": "/bin/amf --amfcfg /free5gc/config/amfcfg.conf",
                    "environment": {
                        "GOTRACEBACK": "crash",
                        "GRPC_GO_LOG_VERBOSITY_LEVEL": "99",
                        "GRPC_GO_LOG_SEVERITY_LEVEL": "info",
                        "GRPC_TRACE": "all",
                        "GRPC_VERBOSITY": "DEBUG",
                        "POD_IP": "1.1.1.1",
                        "MANAGED_BY_CONFIG_POD": "true",
                    },
                }
            }
        }
        updated_plan = self.harness.get_container_pebble_plan(CONTAINER_NAME).to_dict()
        assert expected_plan == updated_plan

    def test_relations_available_and_config_pushed_and_pebble_updated_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_check_output.return_value = b"1.1.1.1"
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == ActiveStatus()

    def test_given_empty_ip_address_when_pebble_ready_then_status_is_waiting(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_check_output.return_value = b""
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.container_pebble_ready(container_name=CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for pod IP address to be available"
        )

    def test_given_no_workload_version_file_when_pebble_ready_then_workload_version_not_set(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.container_pebble_ready(container_name=CONTAINER_NAME)
        self.harness.evaluate_status()
        version = self.harness.get_workload_version()
        assert version is None

    def test_given_workload_version_file_when_pebble_ready_then_workload_version_set(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        expected_version = "1.2.3"
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        os.mkdir(f"{root}/etc")
        (root / "etc/workload-version").write_text(expected_version)
        self.harness.container_pebble_ready(container_name=CONTAINER_NAME)
        self.harness.evaluate_status()
        version = self.harness.get_workload_version()
        assert version == expected_version

    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data == {}

    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data["amf_ip_address"] == "1.1.1.1"
        assert relation_data["amf_hostname"] == "amf.pizza.com"
        assert relation_data["amf_port"] == "38412"

    def test_given_n2_information_and_service_is_running_and_n2_config_is_overriden_when_fiveg_n2_relation_joined_then_custom_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )

        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.update_config(
            {"external-amf-ip": "2.2.2.2", "external-amf-hostname": "amf.burger.com"}
        )
        self.harness.container_pebble_ready(CONTAINER_NAME)

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data["amf_ip_address"] == "2.2.2.2"
        assert relation_data["amf_hostname"] == "amf.burger.com"
        assert relation_data["amf_port"] == "38412"

    def test_given_n2_information_and_service_is_running_and_lb_service_has_no_hostname_when_fiveg_n2_relation_joined_then_internal_service_hostname_is_used(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = None
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.update_config({"external-amf-ip": "2.2.2.2"})
        self.harness.container_pebble_ready(CONTAINER_NAME)

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data["amf_ip_address"] == "2.2.2.2"
        assert (
            relation_data["amf_hostname"] == "sdcore-amf-k8s-external.whatever.svc.cluster.local"
        )
        assert relation_data["amf_port"] == "38412"

    def test_given_n2_information_and_service_is_running_and_metallb_service_is_not_available_when_fiveg_n2_relation_joined_then_amf_goes_in_blocked_state(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = None
        self.mock_k8s_service.get_ip.return_value = None
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == BlockedStatus("Waiting for MetalLB to be enabled")

    def test_given_service_starts_running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.harness.evaluate_status()
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data == {}
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data["amf_ip_address"] == "1.1.1.1"
        assert relation_data["amf_hostname"] == "amf.pizza.com"
        assert relation_data["amf_port"] == "38412"

    def test_given_more_than_one_n2_requirers_join_n2_relation_when_service_starts_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        relation_1_id = self.harness.add_relation(
            relation_name="fiveg-n2", remote_app="n2-requirer-1"
        )
        self.harness.add_relation_unit(
            relation_id=relation_1_id, remote_unit_name="n2-requirer-1/0"
        )
        relation_2_id = self.harness.add_relation(
            relation_name="fiveg-n2", remote_app="n2-requirer-2"
        )
        self.harness.add_relation_unit(
            relation_id=relation_2_id, remote_unit_name="n2-requirer-2/0"
        )
        relation_data = self.harness.get_relation_data(
            relation_id=relation_2_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data["amf_ip_address"] == "1.1.1.1"
        assert relation_data["amf_hostname"] == "amf.pizza.com"
        assert relation_data["amf_port"] == "38412"

    def test_given_can_connect_when_on_pebble_ready_then_private_key_is_generated(
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert (root / "support/TLS/amf.key").read_text() == str(private_key)

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self,
        certificates_relation_id,
    ):
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        self.harness.add_storage(storage_name="certs", attach=True)
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(str(private_key))
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))

        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.charm._on_certificates_relation_broken(event=Mock)

        with pytest.raises(FileNotFoundError):
            (root / "support/TLS/amf.key").read_text()
        with pytest.raises(FileNotFoundError):
            (root / "support/TLS/amf.pem").read_text()

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_status_is_blocked(  # noqa: E501
        self,
        database_relation_id,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        provider_certificate, private_key = self.example_cert_and_key(
            tls_relation_id=certificates_relation_id
        )
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.remove_relation(certificates_relation_id)
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for certificates relation(s)"
        )

    def test_given_certificate_matches_stored_one_when_pebble_ready_then_certificate_is_not_pushed(
        self, database_relation_id
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL

        provider_certificate, private_key = self.example_cert_and_key(tls_relation_id=1)
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(str(private_key))
        (root / "support/TLS/amf.pem").write_text(str(provider_certificate.certificate))

        self.mock_get_assigned_certificate.return_value = provider_certificate, private_key

        self.harness.add_relation(relation_name=NRF_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        assert (root / "support/TLS/amf.pem").read_text() == str(provider_certificate.certificate)

    def test_given_k8s_service_not_created_when_pebble_ready_then_service_is_created(self):
        self.mock_k8s_service.is_created.return_value = False
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.mock_k8s_service.create.assert_called_once()

    def test_given_k8s_service_created_when_remove_then_external_service_is_deleted(self):
        self.mock_k8s_service.is_created.return_value = True
        self.harness.charm.on.remove.emit()

        self.mock_k8s_service.remove.assert_called_once()
