# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from io import StringIO
from unittest.mock import PropertyMock, patch

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
        self.harness.begin()

    def _default_database_is_available(self):
        default_database_relation_id = self.harness.add_relation("default-database", "mongodb")
        self.harness.add_relation_unit(
            relation_id=default_database_relation_id, remote_unit_name="mongodb/0"
        )
        self.harness.update_relation_data(
            relation_id=default_database_relation_id,
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
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for fiveg_nrf relation"),
        )

    def test_given_amf_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for amf-database relation"),
        )

    def test_given_default_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="mongodb")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for default-database relation"),
        )

    def test_given_relations_created_and_default_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the default database to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_created_and_amf_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.side_effect = [True, False]
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the amf database to be available"),
        )

    @patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created"
    )  # noqa: E501
    def test_give_database_info_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for default database info to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_nrf_data_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
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
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
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
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
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
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
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
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        patch_push.assert_not_called()

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
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
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        expected_plan = {
            "services": {
                "amf": {
                    "startup": "enabled",
                    "override": "replace",
                    "command": "/free5gc/amf/amf --amfcfg /free5gc/config/amfcfg.conf",
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
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_relations_available_and_config_pushed_and_pebble_updated_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
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
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus(),
        )

    @patch("charm.check_output")
    def test_given_unit_not_leader_when__fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self, patch_check_output
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.set_leader(is_leader=False)
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("charm.check_output")
    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self, patch_check_output
    ):
        patch_check_output.return_value = b"1.1.1.1"
        self.harness.set_leader(is_leader=True)
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

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
    ):
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        self.harness.set_leader(is_leader=True)
        patch_exists.return_value = True
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
 
        relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="n2-requirer")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="n2-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "sdcore-amf.whatever.svc.cluster.local")
        self.assertEqual(relation_data["amf_port"], "38412")

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock)
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_service_starts__running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
        patch_is_resource_created,
        patch_nrf_url,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
    ):

        self.harness.set_leader(is_leader=True)
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
        patch_exists.return_value = True
        patch_is_resource_created.return_value = True
        patch_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="fiveg_nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
 
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], "1.1.1.1")
        self.assertEqual(relation_data["amf_hostname"], "sdcore-amf.whatever.svc.cluster.local")
        self.assertEqual(relation_data["amf_port"], "38412")

