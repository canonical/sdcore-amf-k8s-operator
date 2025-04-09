# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
from ops import ActionEvent, CharmBase, testing

from lib.charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Provides


class DummyFivegN2ProviderCharm(CharmBase):
    """Dummy charm implementing the provider side of the fiveg_n2 interface."""

    def __init__(self, framework):
        super().__init__(framework)
        self.n2_provider = N2Provides(self, "fiveg-n2")
        framework.observe(
            self.on.set_n2_information_action, self._on_set_n2_information_action
        )

    def _on_set_n2_information_action(self, event: ActionEvent):
        ip_address = event.params.get("ip-address")
        hostname = event.params.get("hostname")
        port = event.params.get("port")
        assert ip_address
        assert hostname
        assert port
        self.n2_provider.set_n2_information(
            amf_ip_address=ip_address,
            amf_hostname=hostname,
            amf_port=port,
        )


class TestFiveGN2Provider:
    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = testing.Context(
            charm_type=DummyFivegN2ProviderCharm,
            meta={
                "name": "n2-provider-charm",
                "provides": {"fiveg-n2": {"interface": "fiveg_n2"}},
            },
            actions={
                "set-n2-information": {
                    "params": {
                        "ip-address": {"type": "string"},
                        "hostname": {"type": "string"},
                        "port": {"type": "string"},
                    },
                },
            },
        )

    def test_given_unit_is_leader_and_data_is_valid_when_set_fiveg_n2_information_then_data_is_in_application_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
        )
        state_in = testing.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        params={
            "ip-address": "192.0.2.1",
            "hostname": "amf",
            "port": "38412",
        }

        state_out = self.ctx.run(self.ctx.on.action("set-n2-information", params=params), state_in)

        relation = state_out.get_relation(fiveg_n2_relation.id)
        assert relation.local_app_data["amf_ip_address"] == "192.0.2.1"
        assert relation.local_app_data["amf_hostname"] == "amf"
        assert relation.local_app_data["amf_port"] == "38412"

    # def test_given_unit_is_not_leader_when_fiveg_n2_relation_joined_then_data_is_not_in_application_databag(  # noqa: E501
    #     self,
    # ):
    #     fiveg_n2_relation = testing.Relation(
    #         endpoint="fiveg-n2",
    #         interface="fiveg_n2",
    #     )
    #     state_in = testing.State(
    #         leader=False,
    #         relations={fiveg_n2_relation},
    #     )
    #
    #     params={
    #         "ip-address": "192.0.2.1",
    #         "hostname": "amf",
    #         "port": "38412",
    #     }
    #
    #     # TODO: Shouldn't this use event.fail() rather than raising an exception?
    #     with pytest.raises(testing.errors.UncaughtCharmError) as e:
    #         self.ctx.run(self.ctx.on.action("set-n2-information", params=params), state_in)
    #
    #     assert "Unit must be leader" in str(e.value)

    def test_given_unit_is_leader_but_port_is_invalid_when_fiveg_n2_relation_joined_then_value_error_is_raised(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
        )
        state_in = testing.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        params={
            "ip-address": "192.0.2.1",
            "hostname": "amf",
            "port": "invalid_port123",
        }

        # TODO: Shouldn't this use event.fail() rather than raising an exception?
        with pytest.raises(testing.errors.UncaughtCharmError) as e:
            self.ctx.run(self.ctx.on.action("set-n2-information", params=params), state_in)

        assert "Invalid relation data" in str(e.value)

    def test_given_unit_is_leader_but_ip_is_invalid_when_fiveg_n2_relation_joined_then_value_error_is_raised(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
        )
        state_in = testing.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        params={
            "ip-address": "invalid.ip.format.123",
            "hostname": "amf",
            "port": "38412",
        }

        # TODO: Shouldn't this use event.fail() rather than raising an exception?
        with pytest.raises(testing.errors.UncaughtCharmError) as e:
            self.ctx.run(self.ctx.on.action("set-n2-information", params=params), state_in)

        assert "Invalid relation data" in str(e.value)
