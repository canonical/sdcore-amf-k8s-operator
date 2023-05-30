# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import patch

from ops import testing
from ops.charm import CharmBase

from lib.charms.sdcore_amf.v0.fiveg_n2 import N2InformationAvailableEvent, N2Requires

METADATA = """
name: fiveg-n2-requirer
description: |
  Dummy charm implementing the requirer side of the fiveg_n2 interface.
summary: |
  Dummy charm implementing the requirer side of the fiveg_n2 interface.
requires:
  fiveg-n2:
    interface: fiveg-n2
"""

logger = logging.getLogger(__name__)


class DummyFivegN2Requires(CharmBase):
    """Dummy charm implementing the requirer side of the fiveg_n2 interface."""

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_requirer = N2Requires(self, "fiveg-n2")
        self.framework.observe(
            self.n2_requirer.on.n2_information_available, self._on_n2_information_available
        )

    def _on_n2_information_available(self, event: N2InformationAvailableEvent):
        logger.info("N2 data, amf_ip_address: %s", self.n2_requirer.amf_ip_address)
        logger.info("N2 data, amf_hostname: %s", self.n2_requirer.amf_hostname)
        logger.info("N2 data, amf_port: %s", self.n2_requirer.amf_port)


class TestFiveGNRFRequirer(unittest.TestCase):
    def setUp(self):
        self.relation_name = "fiveg-n2"
        self.remote_app_name = "dummy-n2-requirer"
        self.remote_unit_name = f"{self.remote_app_name}/0"
        self.harness = testing.Harness(DummyFivegN2Requires, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _create_relation(self, remote_app_name: str):
        relation_id = self.harness.add_relation(
            relation_name=self.relation_name, remote_app=remote_app_name
        )
        self.harness.add_relation_unit(
            relation_id=relation_id, remote_unit_name=f"{remote_app_name}/0"
        )

        return relation_id

    @patch.object(DummyFivegN2Requires, "_on_n2_information_available")
    def test_given_n2_information_in_relation_data_when_relation_changed_then_n2_information_available_event_emitted(  # noqa: E501
        self,
        patch_on_n2_information_available,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_n2_information_available.assert_called()

    @patch.object(DummyFivegN2Requires, "_on_n2_information_available")
    def test_given_n2_information_not_in_relation_data_when_relation_changed_then_n2_information_available_event_is_not_emitted(  # noqa: E501
        self,
        patch_on_n2_information_available,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {}
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_n2_information_available.assert_not_called()

    @patch.object(DummyFivegN2Requires, "_on_n2_information_available")
    def test_given_invalid_n2_information_in_relation_data_when_relation_changed_then_n2_information_available_event_is_not_emitted(  # noqa: E501
        self,
        patch_on_n2_information_available,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "invalid_port123",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_n2_information_available.assert_not_called()

    def test_given_n2_information_in_relation_data_when_get_amf_ip_address_is_called_then_ip_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        amf_ip_address = self.harness.charm.n2_requirer.amf_ip_address
        self.assertEqual(amf_ip_address, "192.168.70.132")

    def test_given_n2_information_in_relation_data_when_get_amf_hostname_is_called_then_host_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        amf_hostname = self.harness.charm.n2_requirer.amf_hostname
        self.assertEqual(amf_hostname, "amf")

    def test_given_n2_information_in_relation_data_when_get_amf_port_is_called_then_port_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        amf_port = self.harness.charm.n2_requirer.amf_port
        self.assertEqual(amf_port, 38412)

    def test_given_n2_information_is_changed_when_get_amf_hostname_is_called_then_new_host_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf2",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        amf_hostname = self.harness.charm.n2_requirer.amf_hostname
        self.assertEqual(amf_hostname, "amf2")

    def test_given_n2_information_is_changed_when_get_amf_port_is_called_then_new_port_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38412",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        relation_data = {
            "amf_ip_address": "192.168.70.132",
            "amf_hostname": "amf",
            "amf_port": "38413",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        amf_port = self.harness.charm.n2_requirer.amf_port
        self.assertEqual(amf_port, 38413)
