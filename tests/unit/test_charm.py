# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from io import StringIO
from unittest.mock import Mock, PropertyMock, call, patch

from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from charm import AMFOperatorCharm


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.namespace = "whatever"
        self.harness = testing.Harness(AMFOperatorCharm)
        self.harness.set_model_name(name=self.namespace)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(is_leader=True)
        self.harness.begin()

    def _database_is_available(self):
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
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for fiveg-nrf relation"),
        )

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation"),
        )

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_amf_charm_in_active_state_when_nrf_relation_breaks_then_status_is_blocked(
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        nrf_relation_id = self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")

        self.harness.remove_relation(nrf_relation_id)

        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for fiveg-nrf relation"),
        )

    def test_given_relations_created_and_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the amf database to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_give_database_info_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for AMF database info to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_nrf_data_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for NRF data to be available"),
        )

    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
        patch_nrf_url,
    ):
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    @patch("ops.model.Container.pull", new=Mock)
    @patch("ops.model.Container.push")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_created_and_database_available_and_nrf_data_available_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_push,
        patch_check_output,
        patch_exists,
    ):
        patch_exists.side_effect = [True, False, True, False]
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
            patch_push.assert_called_with(
                path="/free5gc/config/amfcfg.conf",
                source=expected_content.strip(),
            )

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_content_of_config_file_changed_when_pebble_ready_then_config_file_is_rendered_and_pushed(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO("Dummy Content")
        patch_exists.side_effect = [True, False, True, False]
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
            patch_push.assert_called_with(
                path="/free5gc/config/amfcfg.conf",
                source=expected_content.strip(),
            )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    @patch("ops.model.Container.pull")
    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        patch_pull,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
    ):
        patch_pull.side_effect = [
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
        ]
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.side_effect = [True, False, True, False]
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        patch_push.assert_not_called()

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
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

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_relations_available_and_config_pushed_and_pebble_updated_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus(),
        )

    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("ops.model.Container.exists")
    def test_given_empty_ip_address_when_pebble_ready_then_status_is_waiting(
        self,
        patch_dir_exists,
        patch_nrf_url,
        patch_check_output,
    ):
        patch_check_output.return_value = b""
        patch_nrf_url.return_value = "http://nrf:8081"
        patch_dir_exists.return_value = True
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()

        self.harness.container_pebble_ready(container_name="amf")

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
            status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
        patch_get,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "amf.pizza.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_and_n2_config_is_overriden_when_fiveg_n2_relation_joined_then_custom_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
        patch_get,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.update_config({"amf-ip": "2.2.2.2", "amf-hostname": "amf.burger.com"})
        self._database_is_available()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "2.2.2.2")
        self.assertEqual(relation_data["amf_hostname"], "amf.burger.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_n2_information_and_service_is_running_and_lb_service_has_no_hostname_when_fiveg_n2_relation_joined_then_internal_service_hostname_is_used(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
        patch_get,
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", spec=["ip"])])))
        patch_get.return_value = service
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.update_config({"amf-ip": "2.2.2.2"})
        self._database_is_available()
        self.harness.container_pebble_ready("amf")

        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "2.2.2.2")
        self.assertEqual(
            relation_data["amf_hostname"], "sdcore-amf-external.whatever.svc.cluster.local"
        )
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_service_starts_running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
        patch_get,
    ):
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
        self.harness.container_pebble_ready("amf")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "amf.pizza.com")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_more_than_one_n2_requirers_join_n2_relation_when_service_starts_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
        patch_get,
    ):
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        service = Mock(
            status=Mock(loadbalancer=Mock(ingress=[Mock(ip="1.1.1.1", hostname="amf.pizza.com")]))
        )
        patch_get.return_value = service
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg-nrf", remote_app="nrf")
        self._database_is_available()
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

    @patch("charm.generate_private_key")
    @patch("ops.model.Container.push")
    def test_given_can_connect_when_on_certificates_relation_created_then_private_key_is_generated(
        self, patch_push, patch_generate_private_key
    ):
        private_key = b"whatever key content"
        self.harness.set_can_connect(container="amf", val=True)
        patch_generate_private_key.return_value = private_key

        self.harness.charm._on_certificates_relation_created(event=Mock)

        patch_push.assert_called_with(path="/support/TLS/amf.key", source=private_key.decode())

    @patch("ops.model.Container.remove_path")
    @patch("ops.model.Container.exists")
    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self, patch_exists, patch_remove_path
    ):
        patch_exists.return_value = True
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificates_relation_broken(event=Mock)

        patch_remove_path.assert_any_call(path="/support/TLS/amf.pem")
        patch_remove_path.assert_any_call(path="/support/TLS/amf.key")
        patch_remove_path.assert_any_call(path="/support/TLS/amf.csr")

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
        new=Mock,
    )
    @patch("ops.model.Container.push")
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    def test_given_private_key_exists_when_on_certificates_relation_joined_then_csr_is_generated(
        self, patch_exists, patch_pull, patch_generate_csr, patch_push
    ):
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        patch_pull.return_value = StringIO("private key content")
        patch_exists.return_value = True
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificates_relation_joined(event=Mock)

        patch_push.assert_called_with(path="/support/TLS/amf.csr", source=csr.decode())

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    def test_given_private_key_exists_when_on_certificates_relation_joined_then_cert_is_requested(
        self,
        patch_exists,
        patch_pull,
        patch_generate_csr,
        patch_request_certificate_creation,
    ):
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        patch_pull.return_value = StringIO("private key content")
        patch_exists.return_value = True
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificates_relation_joined(event=Mock)

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_csr_matches_stored_one_when_certificate_available_then_certificate_is_pushed(
        self,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        csr = "Whatever CSR content"
        patch_pull.return_value = StringIO(csr)
        patch_exists.return_value = True
        certificate = "Whatever certificate content"
        event = Mock()
        event.certificate = certificate
        event.certificate_signing_request = csr
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_available(event=event)

        patch_push.assert_called_with(path="/support/TLS/amf.pem", source=certificate)

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_csr_doesnt_match_stored_one_when_certificate_available_then_certificate_is_not_pushed(  # noqa: E501
        self,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO("Stored CSR content")
        patch_exists.return_value = True
        certificate = "Whatever certificate content"
        event = Mock()
        event.certificate = certificate
        event.certificate_signing_request = "Relation CSR content (different from stored one)"
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_available(event=event)

        patch_push.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    def test_given_certificate_does_not_match_stored_one_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self, patch_pull, patch_generate_csr, patch_request_certificate_creation
    ):
        event = Mock()
        patch_pull.return_value = StringIO("Stored certificate content")
        event.certificate = "Relation certificate content (different from stored)"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    def test_given_certificate_matches_stored_one_when_certificate_expiring_then_certificate_is_requested(  # noqa: E501
        self, patch_pull, patch_generate_csr, patch_request_certificate_creation
    ):
        certificate = "whatever certificate content"
        event = Mock()
        event.certificate = certificate
        patch_pull.return_value = StringIO(certificate)
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="amf", val=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.create")
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
                )
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
