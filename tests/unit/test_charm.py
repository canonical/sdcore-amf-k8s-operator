# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, PropertyMock, call, patch

from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from ops import ActiveStatus, BlockedStatus, WaitingStatus, testing

from charm import AMFOperatorCharm
from lib.charms.tls_certificates_interface.v3.tls_certificates import ProviderCertificate


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.namespace = "whatever"
        self.harness = testing.Harness(AMFOperatorCharm)
        self.harness.set_model_name(name=self.namespace)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(is_leader=True)
        self.harness.begin()

    def _create_database_relation_and_populate_data(self) -> int:
        database_relation_id = self.harness.add_relation("database", "mongodb")
        self.harness.add_relation_unit(
            relation_id=database_relation_id, remote_unit_name="mongodb/0"
        )
        self.harness.update_relation_data(
            relation_id=database_relation_id,
            app_or_unit="mongodb",
            key_values={
                "username": "dummy",
                "password": "dummy",
                "uris": "http://dummy",
            },
        )
        return database_relation_id

    @staticmethod
    def _read_file(path: str) -> str:
        """Reads a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content

    def test_given_fiveg_nrf_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for fiveg_nrf relation"),
        )

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation"),
        )

    def test_given_certificates_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for certificates relation"),
        )

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_amf_charm_in_active_state_when_nrf_relation_breaks_then_status_is_blocked(
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        nrf_relation_id = self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        self.harness.remove_relation(nrf_relation_id)
        self.harness.evaluate_status()

        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for fiveg_nrf relation"),
        )

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_amf_charm_in_active_state_when_database_relation_breaks_then_status_is_blocked(
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        database_relation_id = self._create_database_relation_and_populate_data()
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.container_pebble_ready("amf")

        self.harness.remove_relation(database_relation_id)
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation"),
        )

    @patch("charm.generate_private_key")
    def test_given_relations_created_and_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self, patch_generate_private_key
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the amf database to be available"),
        )

    @patch("charm.generate_private_key")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_database_info_not_available_when_pebble_ready_then_status_is_waiting(
        self, patch_is_resource_created, patch_generate_private_key
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for AMF database info to be available"),
        )

    @patch("charm.generate_private_key")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_nrf_data_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
        patch_generate_private_key,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for NRF data to be available"),
        )

    @patch("charm.generate_private_key")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self, patch_is_resource_created, patch_nrf_url, patch_generate_private_key
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charm.generate_private_key")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_certificates_not_stored_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_generate_private_key,
        patch_check_output,
        patch_generate_csr,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for certificates to be stored"),
        )

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charm.generate_private_key")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_created_and_database_available_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_generate_private_key,
        patch_check_output,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        patch_check_output.return_value = b"1.1.1.1"
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        self._create_database_relation_and_populate_data()

        self.harness.container_pebble_ready("amf")
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
        self.assertEqual((root / "support/TLS/amf.key").read_text(), private_key.decode())
        self.assertEqual((root / "support/TLS/amf.pem").read_text(), certificate)
        self.assertEqual(
            (root / "free5gc/config/amfcfg.conf").read_text(), expected_content.strip()
        )

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charm.generate_private_key")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_generate_private_key,
        patch_check_output,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        root = self.harness.get_filesystem_root("amf")
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        config_modification_time = (root / "free5gc/config/amfcfg.conf").stat().st_mtime
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            (root / "free5gc/config/amfcfg.conf").stat().st_mtime, config_modification_time
        )

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        expected_plan = {
            "services": {
                "amf": {
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
        updated_plan = self.harness.get_container_pebble_plan("amf").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_relations_available_and_config_pushed_and_pebble_updated_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        patch_check_output.return_value = b"1.1.1.1"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus(),
        )

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    def test_given_empty_ip_address_when_pebble_ready_then_status_is_waiting(
        self,
        patch_nrf_url,
        patch_check_output,
    ):
        self.harness.add_storage(storage_name="config", attach=True)
        patch_check_output.return_value = b""
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()

        self.harness.container_pebble_ready(container_name="amf")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for pod IP address to be available"),
        )

    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_get
    ):
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "amf.pizza.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_and_n2_config_is_overriden_when_fiveg_n2_relation_joined_then_custom_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.update_config(
            {"external-amf-ip": "2.2.2.2", "external-amf-hostname": "amf.burger.com"}
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "2.2.2.2")
        self.assertEqual(relation_data["amf_hostname"], "amf.burger.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_and_lb_service_has_no_hostname_when_fiveg_n2_relation_joined_then_internal_service_hostname_is_used(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", spec=["ip"])])))
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self.harness.update_config({"external-amf-ip": "2.2.2.2"})
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "2.2.2.2")
        self.assertEqual(
            relation_data["amf_hostname"], "sdcore-amf-k8s-external.whatever.svc.cluster.local"
        )
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_and_metallb_service_is_not_available_when_fiveg_n2_relation_joined_then_amf_goes_in_blocked_state(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(status=Mock(loadBalancer=Mock(ingress=None)))
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Waiting for MetalLB to be enabled")
        )

    # This one needs
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_service_starts_running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.harness.evaluate_status()
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "amf.pizza.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    # this is good
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("charm.generate_private_key")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_more_than_one_n2_requirers_join_n2_relation_when_service_starts_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_generate_private_key,
        patch_get,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "free5gc/config/amfcfg.conf").write_text(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadBalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

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
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "amf.pizza.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.generate_csr")
    @patch("charm.check_output")
    @patch("charm.generate_private_key")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_can_connect_when_on_pebble_ready_then_private_key_is_generated(
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_generate_private_key,
        patch_check_output,
        patch_generate_csr,
        patch_get_assigned_certificates,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        private_key = b"whatever key content"
        patch_generate_private_key.return_value = private_key
        certificate = "Whatever certificate content"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")
        self.harness.evaluate_status()
        self.assertEqual((root / "support/TLS/amf.key").read_text(), private_key.decode())

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        private_key = b"whatever key content"
        csr = b"Whatever CSR content"
        certificate = "Whatever certificate content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key.decode())
        (root / "support/TLS/amf.csr").write_text(csr.decode())
        (root / "support/TLS/amf.pem").write_text(certificate)

        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificates_relation_broken(event=Mock)

        with self.assertRaises(FileNotFoundError):
            (root / "support/TLS/amf.key").read_text()
        with self.assertRaises(FileNotFoundError):
            (root / "support/TLS/amf.pem").read_text()
        with self.assertRaises(FileNotFoundError):
            (root / "support/TLS/amf.csr").read_text()

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_status_is_blocked(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        certificate = "Whatever certificate content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.pem").write_text(certificate)
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        cert_rel_id = self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.remove_relation(cert_rel_id)
        self.harness.evaluate_status()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Waiting for certificates relation")
        )

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
        new=Mock,
    )
    @patch("charm.generate_csr")
    def test_given_private_key_exists_when_pebble_ready_then_csr_is_generated(
        self,
        patch_generate_csr,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        patch_nrf_url.return_value = "http://nrf:8081"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        private_key = "private key content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key)
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.container_pebble_ready("amf")

        self.assertEqual((root / "support/TLS/amf.csr").read_text(), csr.decode())

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
    )
    @patch("charm.generate_csr")
    def test_given_private_key_exists_and_cert_not_yet_requested_when_pebble_ready_then_cert_is_requested(  # noqa: E501
        self,
        patch_generate_csr,
        patch_request_certificate_creation,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        patch_nrf_url.return_value = "http://nrf:8081"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        private_key = "private key content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key)

        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.container_pebble_ready("amf")

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
    )
    def test_given_cert_already_stored_when_pebble_ready_then_cert_is_not_requested(  # noqa: E501
        self,
        patch_request_certificate_creation,
        patch_nrf_url,
        patch_check_output,
        patch_get_assigned_certificates,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        patch_nrf_url.return_value = "http://nrf:8081"
        private_key = "whatever key content"
        csr = b"Whatever CSR content"
        certificate = "Whatever certificate content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.pem").write_text(certificate)
        (root / "support/TLS/amf.csr").write_text(csr.decode())
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.container_pebble_ready("amf")

        patch_request_certificate_creation.assert_not_called()

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    def test_given_csr_matches_stored_one_when_pebble_ready_then_certificate_is_pushed(
        self,
        patch_get_assigned_certificates,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        patch_nrf_url.return_value = "http://nrf:8081"
        private_key = "whatever key content"
        csr = b"Whatever CSR content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.csr").write_text(csr.decode())
        certificate = "Whatever certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.container_pebble_ready("amf")

        self.assertEqual((root / "support/TLS/amf.pem").read_text(), certificate)

    @patch("charm.check_output")
    @patch("charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.get_assigned_certificates",  # noqa: E501
    )
    def test_given_certificate_matches_stored_one_when_pebble_ready_then_certificate_is_not_pushed(
        self,
        patch_get_assigned_certificates,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage(storage_name="certs", attach=True)
        self.harness.add_storage(storage_name="config", attach=True)
        patch_nrf_url.return_value = "http://nrf:8081"
        private_key = "whatever key content"
        csr = b"Whatever CSR content"
        root = self.harness.get_filesystem_root("amf")
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.csr").write_text(csr.decode())
        certificate = "Whatever certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        provider_certificate = Mock(ProviderCertificate)
        provider_certificate.certificate = certificate
        provider_certificate.csr = csr.decode()
        patch_get_assigned_certificates.return_value = [
            provider_certificate,
        ]

        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(
            relation_name="certificates", remote_app="tls-certificates-operator"
        )
        self._create_database_relation_and_populate_data()
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.container_pebble_ready("amf")

        self.assertEqual((root / "support/TLS/amf.pem").read_text(), certificate)

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
    )
    @patch("charm.generate_csr")
    def test_given_certificate_does_not_match_stored_one_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self, patch_generate_csr, patch_request_certificate_creation
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        event = Mock()
        root = self.harness.get_filesystem_root("amf")
        certificate = "Stored certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        event.certificate = "Relation certificate content (different from stored)"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
    )
    @patch("charm.generate_csr")
    def test_given_amf_cannot_connect_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self, patch_generate_csr, patch_request_certificate_creation
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        event = Mock()
        root = self.harness.get_filesystem_root("amf")
        certificate = "Stored certificate content"
        (root / "support/TLS/amf.pem").write_text(certificate)
        event.certificate = certificate
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="amf", val=False)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v3.tls_certificates.TLSCertificatesRequiresV3.request_certificate_creation",  # noqa: E501
    )
    @patch("charm.generate_csr")
    def test_given_certificate_matches_stored_one_when_certificate_expiring_then_certificate_is_requested(  # noqa: E501
        self, patch_generate_csr, patch_request_certificate_creation
    ):
        self.harness.add_storage(storage_name="certs", attach=True)
        root = self.harness.get_filesystem_root("amf")
        private_key = "whatever key content"
        certificate = "whatever certificate content"
        (root / "support/TLS/amf.key").write_text(private_key)
        (root / "support/TLS/amf.pem").write_text(certificate)
        event = Mock()
        event.certificate = certificate
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.apply")
    def test_when_install_then_external_service_is_created(self, patch_create):
        self.harness.charm.on.install.emit()

        calls = [
            call(
                Service(
                    apiVersion="v1",
                    kind="Service",
                    metadata=ObjectMeta(
                        namespace=self.namespace,
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

        patch_create.assert_has_calls(calls=calls)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.delete")
    def test_when_remove_then_external_service_is_deleted(self, patch_delete):
        self.harness.charm.on.remove.emit()

        calls = [
            call(
                Service,
                namespace=self.namespace,
                name=f"{self.harness.charm.app.name}-external",
            ),
        ]

        patch_delete.assert_has_calls(calls=calls)
