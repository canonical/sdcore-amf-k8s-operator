# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import PropertyMock, patch

import pytest
from ops import testing
from ops.charm import CharmBase, RelationJoinedEvent

from lib.charms.sdcore_amf.v0.fiveg_n2 import N2Provides

METADATA = """
name: fiveg-n2-provider
description: |
  Dummy charm implementing the provider side of the fiveg_n2 interface.
summary: |
  Dummy charm implementing the provider side of the fiveg_n2 interface.
provides:
  fiveg-n2:
    interface: fiveg-n2
"""


class DummyFivegN2ProviderCharm(CharmBase):
    """Dummy charm implementing the provider side of the fiveg_n2 interface."""

    HOST = "amf"
    PORT = 38412
    IP_ADDRESS = "192.168.70.132"

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_provider = N2Provides(self, "fiveg-n2")
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._on_fiveg_n2_relation_joined)

    def _on_fiveg_n2_relation_joined(self, event: RelationJoinedEvent):
        if self.unit.is_leader():
            self.n2_provider.set_n2_information(
                amf_ip_address=self.IP_ADDRESS,
                amf_hostname=self.HOST,
                amf_port=self.PORT,
            )


class TestFiveGN2Provider(unittest.TestCase):
    def setUp(self):
        self.relation_name = "fiveg-n2"
        self.remote_app_name = "dummy-n2-requirer"
        self.remote_unit_name = f"{self.remote_app_name}/0"
        self.harness = testing.Harness(DummyFivegN2ProviderCharm, meta=METADATA)
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

    def test_given_unit_is_leader_and_data_is_valid_when_fiveg_n2_relation_joined_then_data_is_in_application_databag(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        expected_host = "amf"
        expected_port = 38412
        expected_ip_address = "192.168.70.132"

        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["amf_ip_address"], expected_ip_address)
        self.assertEqual(relation_data["amf_hostname"], expected_host)
        self.assertEqual(relation_data["amf_port"], str(expected_port))

    def test_given_unit_is_not_leader_when_fiveg_n2_relation_joined_then_data_is_not_in_application_databag(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=False)

        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    def test_given_unit_is_leader_but_port_is_invalid_when_fiveg_n2_relation_joined_then_value_error_is_raised(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        with patch.object(
            DummyFivegN2ProviderCharm, "PORT", new_callable=PropertyMock
        ) as patched_port:
            patched_port.return_value = "invalid_port123"
            with pytest.raises(ValueError):
                self._create_relation(remote_app_name=self.remote_app_name)

    def test_given_unit_is_leader_but_ip_is_invalid_when_fiveg_n2_relation_joined_then_value_error_is_raised(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        with patch.object(
            DummyFivegN2ProviderCharm, "IP_ADDRESS", new_callable=PropertyMock
        ) as patched_ip_address:
            patched_ip_address.return_value = "invalid.ip.format.123"
            with pytest.raises(ValueError):
                self._create_relation(remote_app_name=self.remote_app_name)
