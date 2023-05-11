# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import unittest
from unittest.mock import patch

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

    def test_given_nrf_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for nrf relation"),
        )

    def test_given_amf_database_relation_not_created_when_pebble_ready_then_status_is_blocked(
        self,
    ):
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="mongodb")
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
        self.harness.add_relation(relation_name="nrf", remote_app="mongodb")
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
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the default database to start"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_created_and_amf_database_not_available_when_pebble_ready_then_status_is_waiting(  # noqa: E501
        self,
        patched_is_resource_created,
    ):
        patched_is_resource_created.side_effect = [True, False]
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self.harness.add_relation(relation_name="default-database", remote_app="mongodb")
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the amf database to start"),
        )

    @patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created"
    )  # noqa: E501
    def test_give_database_info_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patched_is_resource_created,
    ):
        patched_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
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
        patched_is_resource_created,
    ):
        patched_is_resource_created.return_value = True
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for NRF data to be available"),
        )

    @patch("charm.check_output")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.get_nrf_url")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relations_created_and_database_available_and_nrf_data_available_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
        patched_is_resource_created,
        patched_get_nrf_url,
        patch_push,
        patch_exists,
        patch_check_output,
    ):
        patch_check_output.return_value = "1.1.1.1".encode()
        patch_exists.return_value = False
        patched_is_resource_created.return_value = True
        patched_get_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        with open("tests/unit/expected_config/config.conf") as expected_bundle_file:
            expected_content = expected_bundle_file.read()
            patch_push.assert_called_with(
                path="/free5gc/config/amfcfg.conf",
                source=expected_content,
            )

    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("ops.model.Container.exists")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.get_nrf_url")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_relation_available_and_config_pushed_when_pebble_ready_then_pebble_layer_is_added_correctly(  # noqa: E501
        self,
        patched_is_resource_created,
        patched_get_nrf_url,
        patch_exists,
        patch_check_output,
        patch_push,
    ):
        patch_check_output.return_value = "1.1.1.1".encode()
        patch_exists.return_value = False
        patched_is_resource_created.return_value = True
        patched_get_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
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
        self.harness.container_pebble_ready("amf")
        updated_plan = self.harness.get_container_pebble_plan("amf").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch("ops.model.Container.exists")
    @patch("charms.sdcore_nrf.v0.fiveg_nrf.NRFRequires.get_nrf_url")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_relations_available_and_config_pushed_and_pebble_updated_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patched_is_resource_created,
        patched_get_nrf_url,
        patch_exists,
        patch_check_output,
        patch_push,
    ):
        patch_check_output.return_value = "1.1.1.1".encode()
        patch_exists.return_value = False
        patched_is_resource_created.return_value = True
        patched_get_nrf_url.return_value = "http://nrf:8081"
        self.harness.set_can_connect(container="amf", val=True)
        self.harness.add_relation(relation_name="nrf", remote_app="nrf")
        self.harness.add_relation(relation_name="amf-database", remote_app="mongodb")
        self._default_database_is_available()
        self.harness.container_pebble_ready("amf")
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus(),
        )
