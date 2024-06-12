# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import Mock, PropertyMock, call, patch

import pytest
from charm import AMFOperatorCharm
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from ops import ActiveStatus, BlockedStatus, WaitingStatus, testing

from lib.charms.tls_certificates_interface.v3.tls_certificates import ProviderCertificate

CONTAINER_NAME = "amf"
DB_APPLICATION_NAME = "mongodb-k8s"
NRF_APPLICATION_NAME = "nrf"
NRF_RELATION_NAME = "fiveg_nrf"
NRF_URL = "http://nrf:8081"
WEBUI_URL = "sdcore-webui:9876"
SDCORE_CONFIG_RELATION_NAME = "sdcore_config"
WEBUI_APPLICATION_NAME = "sdcore-webui-operator"
TLS_APPLICATION_NAME = "tls-certificates-operator"
TLS_RELATION_NAME = "certificates"
NAMESPACE = "whatever"
PRIVATE_KEY = b"whatever key content"
CSR = b"whatever csr content"
CERTIFICATE = "Whatever certificate content"


class TestCharm:
    patcher_check_output = patch("charm.check_output")
    patcher_nrf_url = patch(
        "charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url",
        new_callable=PropertyMock
    )
    patcher_webui_url = patch(
        "charms.sdcore_webui_k8s.v0.sdcore_config.SdcoreConfigRequires.webui_url",
        new_callable=PropertyMock
    )
    patcher_generate_csr = patch("charm.generate_csr")
    patcher_generate_private_key = patch("charm.generate_private_key")
    patcher_get_assigned_certificates = patch("charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates")  # noqa: E501
    patcher_request_certificate_creation = patch("charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation")  # noqa: E501
    patcher_client = patch("lightkube.core.client.GenericSyncClient", new=Mock)
    patcher_get = patch("lightkube.core.client.Client.get")
    patcher_apply = patch("lightkube.core.client.Client.apply")
    patcher_delete = patch("lightkube.core.client.Client.delete")

    @pytest.fixture()
    def setup(self):
        self.mock_generate_csr = TestCharm.patcher_generate_csr.start()
        self.mock_generate_private_key = TestCharm.patcher_generate_private_key.start()
        self.mock_get_assigned_certificates = TestCharm.patcher_get_assigned_certificates.start()
        self.mock_request_certificate_creation = TestCharm.patcher_request_certificate_creation.start()  # noqa: E501
        self.mock_nrf_url = TestCharm.patcher_nrf_url.start()
        self.mock_webui_url = TestCharm.patcher_webui_url.start()
        self.mock_check_output = TestCharm.patcher_check_output.start()
        TestCharm.patcher_client.start()
        self.mock_get = TestCharm.patcher_get.start()
        self.mock_apply = TestCharm.patcher_apply.start()
        self.mock_delete = TestCharm.patcher_delete.start()

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def harness(self, setup, request):
        self.harness = testing.Harness(AMFOperatorCharm)
        self.harness.set_model_name(name=NAMESPACE)
        self.harness.set_leader(is_leader=True)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.teardown)

    @pytest.fixture()
    def nrf_relation_id(self) -> int:
        yield self.harness.add_relation(
            relation_name=NRF_RELATION_NAME,
            remote_app=DB_APPLICATION_NAME,
        )

    @pytest.fixture()
    def certificates_relation_id(self) -> int:
        yield self.harness.add_relation(
            relation_name=TLS_RELATION_NAME,
            remote_app=TLS_APPLICATION_NAME,
        )

    @pytest.fixture()
    def sdcore_config_relation_id(self) -> int:
        sdcore_config_relation_id = self.harness.add_relation(
            relation_name=SDCORE_CONFIG_RELATION_NAME,
            remote_app=WEBUI_APPLICATION_NAME,
        )
        self.harness.add_relation_unit(
            relation_id=sdcore_config_relation_id, remote_unit_name=f"{WEBUI_APPLICATION_NAME}/0"
        )
        self.harness.update_relation_data(
            relation_id=sdcore_config_relation_id,
            app_or_unit=WEBUI_APPLICATION_NAME,
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

    def test_given_fiveg_nrf_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, certificates_relation_id, sdcore_config_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus("Waiting for fiveg_nrf relation(s)")

    def test_given_certificates_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, nrf_relation_id, sdcore_config_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for certificates relation(s)"
        )

    def test_given_sdcore_config_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self, nrf_relation_id, certificates_relation_id
    ):
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for sdcore_config relation(s)"
        )

    def test_given_amf_charm_in_active_state_when_nrf_relation_breaks_then_status_is_blocked(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.harness.remove_relation(nrf_relation_id)
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus("Waiting for fiveg_nrf relation(s)")

    def test_given_amf_charm_in_active_state_when_sdcore_config_relation_breaks_then_status_is_blocked(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.harness.remove_relation(sdcore_config_relation_id)
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus(
            "Waiting for sdcore_config relation(s)"
        )

    def test_given_nrf_data_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_nrf_url.return_value = ""
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus("Waiting for NRF data to be available")  # noqa: E501

    def test_given_webui_data_not_available_when_pebble_ready_then_status_is_waiting(
        self, nrf_relation_id, certificates_relation_id
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.add_relation(
            relation_name=SDCORE_CONFIG_RELATION_NAME,
            remote_app=WEBUI_APPLICATION_NAME,
        )
        self.mock_webui_url.return_value = ""
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus("Waiting for Webui data to be available")  # noqa: E501

    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus("Waiting for storage to be attached")  # noqa: E501

    def test_given_certificates_not_stored_when_pebble_ready_then_status_is_waiting(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == WaitingStatus("Waiting for certificates to be stored")  # noqa: E501

    def test_given_relations_created_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_check_output.return_value = b"1.1.1.1"
        certificate = "Whatever certificate content"
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_webui_url.return_value = WEBUI_URL
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(certificate)

        self.harness.container_pebble_ready(CONTAINER_NAME)
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
        assert (root / "support/TLS/amf.key").read_text() == PRIVATE_KEY.decode()
        assert (root / "support/TLS/amf.pem").read_text() == certificate
        assert (root / "free5gc/config/amfcfg.conf").read_text() == expected_content.strip()

    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        config_modification_time = (root / "free5gc/config/amfcfg.conf").stat().st_mtime
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_webui_url.return_value = WEBUI_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        assert (root / "free5gc/config/amfcfg.conf").stat().st_mtime == config_modification_time

    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
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
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.model.unit.status == ActiveStatus()

    def test_given_empty_ip_address_when_pebble_ready_then_status_is_waiting(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_check_output.return_value = b""
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.container_pebble_ready(container_name=CONTAINER_NAME)
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == WaitingStatus("Waiting for pod IP address to be available")  # noqa: E501

    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        self.mock_get.return_value = service
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        assert relation_data == {}

    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        self.mock_get.return_value = service
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
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        self.mock_get.return_value = service
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
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", spec=["ip"])])))
        self.mock_get.return_value = service
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
        assert relation_data["amf_hostname"] == "sdcore-amf-k8s-external.whatever.svc.cluster.local"  # noqa: E501
        assert relation_data["amf_port"] == "38412"

    def test_given_n2_information_and_service_is_running_and_metallb_service_is_not_available_when_fiveg_n2_relation_joined_then_amf_goes_in_blocked_state(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(status=Mock(loadBalancer=Mock(ingress=None)))
        self.mock_get.return_value = service
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == BlockedStatus("Waiting for MetalLB to be enabled")

    def test_given_service_starts_running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
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
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        self.mock_get.return_value = service
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
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        self.mock_get.return_value = service
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_generate_private_key.return_value = PRIVATE_KEY
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
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        private_key = b"whatever key content"
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        certificate = "Whatever certificate content"
        self.mock_generate_csr.return_value = CSR
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(certificate)
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_nrf_url.return_value = NRF_URL
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)
        self.harness.evaluate_status()
        assert (root / "support/TLS/amf.key").read_text() == private_key.decode()

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        certificate = "Whatever certificate content"
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(PRIVATE_KEY.decode())
        (root / "support/TLS/amf.csr").write_text(CSR.decode())
        (root / "support/TLS/amf.pem").write_text(certificate)

        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.charm._on_certificates_relation_broken(event=Mock)

        with pytest.raises(FileNotFoundError):
            (root / "support/TLS/amf.key").read_text()
        with pytest.raises(FileNotFoundError):
            (root / "support/TLS/amf.pem").read_text()
        with pytest.raises(FileNotFoundError):
            (root / "support/TLS/amf.csr").read_text()

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_status_is_blocked(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_generate_private_key.return_value = PRIVATE_KEY
        self.mock_generate_csr.return_value = CSR
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.remove_relation(certificates_relation_id)
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for certificates relation(s)"
        )

    def test_given_private_key_exists_when_pebble_ready_then_csr_is_generated(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_generate_csr.return_value = CSR
        private_key = "private key content"
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(private_key)
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.container_pebble_ready(CONTAINER_NAME)

        assert (root / "support/TLS/amf.csr").read_text() == CSR.decode()

    def test_given_private_key_exists_and_cert_not_yet_requested_when_pebble_ready_then_cert_is_requested(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL
        self.mock_generate_csr.return_value = CSR
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(PRIVATE_KEY.decode())

        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.mock_request_certificate_creation.assert_called_with(certificate_signing_request=CSR)

    def test_given_cert_already_stored_when_pebble_ready_then_cert_is_not_requested(  # noqa: E501
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(PRIVATE_KEY.decode())
        (root / "support/TLS/amf.pem").write_text(CERTIFICATE)
        (root / "support/TLS/amf.csr").write_text(CSR.decode())
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = CERTIFICATE
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        self.mock_request_certificate_creation.assert_not_called()

    def test_given_csr_matches_stored_one_when_pebble_ready_then_certificate_is_pushed(
        self,
        nrf_relation_id,
        certificates_relation_id,
        sdcore_config_relation_id,
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL
        private_key = "whatever key content"
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.csr").write_text(CSR.decode())
        certificate = "Whatever certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        assert (root / "support/TLS/amf.pem").read_text() == certificate

    def test_given_certificate_matches_stored_one_when_pebble_ready_then_certificate_is_not_pushed(
        self
    ):
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        self.mock_nrf_url.return_value = NRF_URL
        private_key = "whatever key content"
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.csr").write_text(CSR.decode())
        certificate = "Whatever certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = CSR.decode()
        self.mock_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.add_relation(relation_name=NRF_RELATION_NAME, remote_app=DB_APPLICATION_NAME)
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)
        self.harness.container_pebble_ready(CONTAINER_NAME)

        assert (root / "support/TLS/amf.pem").read_text() == certificate

    def test_given_certificate_does_not_match_stored_one_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        event = Mock()
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        certificate = "Stored certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        event.certificate = "Relation certificate content (different from stored)"
        self.mock_generate_csr.return_value = CSR
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        self.mock_request_certificate_creation.assert_not_called()

    def test_given_amf_cannot_connect_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        event = Mock()
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        certificate = "Stored certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        event.certificate = certificate
        self.mock_generate_csr.return_value = CSR
        self.harness.set_can_connect(container=CONTAINER_NAME, val=False)

        self.harness.charm._on_certificate_expiring(event=event)

        self.mock_request_certificate_creation.assert_not_called()

    def test_given_certificate_matches_stored_one_when_certificate_expiring_then_certificate_is_requested(  # noqa: E501
        self
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        root = self.harness.get_filesystem_root(CONTAINER_NAME)
        private_key = "whatever key content"
        certificate = "whatever certificate content"
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.pem").write_text(certificate)
        event = Mock()
        event.certificate = certificate
        self.mock_generate_csr.return_value = CSR
        self.harness.set_can_connect(container=CONTAINER_NAME, val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        self.mock_request_certificate_creation.assert_called_with(certificate_signing_request=CSR)

    def test_when_install_then_external_service_is_created(self):
        self.harness.charm.on.install.emit()

        calls = [
            call(
                Service(
                    apiVersion="v1",
                    kind="Service",
                    metadata=ObjectMeta(
                        namespace=NAMESPACE,
                        name=f"{self.harness.charm.app.name}-external",
                    ),
                    spec=ServiceSpec(
                        selector={"app.kubernetes.io/name": self.harness.charm.app.name},
                        ports=[
                            ServicePort(
                                name="ngapp",
                                port=38412,
                                protocol="SCTP",
                            ),
                        ],
                        type="LoadBalancer",
                    ),
                ),
                field_manager="sdcore-amf-k8s",
            ),
        ]

        self.mock_apply.assert_has_calls(calls=calls)

    def test_when_remove_then_external_service_is_deleted(self):
        self.harness.charm.on.remove.emit()

        calls = [
            call(
                Service,
                namespace=NAMESPACE,
                name=f"{self.harness.charm.app.name}-external",
            ),
        ]

        self.mock_delete.assert_has_calls(calls=calls)
