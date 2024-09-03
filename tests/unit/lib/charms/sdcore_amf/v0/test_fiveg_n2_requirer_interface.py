# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
import scenario
from ops import ActionEvent, CharmBase

from lib.charms.sdcore_amf_k8s.v0.fiveg_n2 import N2InformationAvailableEvent, N2Requires


class DummyFivegN2Requires(CharmBase):
    """Dummy charm implementing the requirer side of the fiveg_n2 interface."""

    def __init__(self, framework):
        super().__init__(framework)
        self.n2_requirer = N2Requires(self, "fiveg-n2")
        framework.observe(
            self.on.get_n2_information_action, self._on_get_n2_information_action
        )

    def _on_get_n2_information_action(self, event: ActionEvent):
        event.set_results(
            results={
                "amf-ip-address": self.n2_requirer.amf_ip_address,
                "amf-hostname": self.n2_requirer.amf_hostname,
                "amf-port": str(self.n2_requirer.amf_port),
            }
        )


class TestFiveGNRFRequirer:
    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=DummyFivegN2Requires,
            meta={
                "name": "n2-requirer-charm",
                "requires": {"fiveg-n2": {"interface": "fiveg_n2"}},
            },
            actions={
                "get-n2-information": {},
            },
        )

    def test_given_n2_information_in_relation_data_when_relation_changed_then_n2_information_available_event_emitted(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
            remote_app_data={
                "amf_ip_address": "192.168.70.132",
                "amf_hostname": "amf",
                "amf_port": "38412",
            },
        )
        state_in = scenario.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        self.ctx.run(self.ctx.on.relation_changed(fiveg_n2_relation), state_in)

        assert len(self.ctx.emitted_events) == 2
        assert isinstance(self.ctx.emitted_events[1], N2InformationAvailableEvent)
        assert self.ctx.emitted_events[1].amf_ip_address == "192.168.70.132"
        assert self.ctx.emitted_events[1].amf_hostname == "amf"
        assert self.ctx.emitted_events[1].amf_port == "38412"

    def test_given_n2_information_not_in_relation_data_when_relation_changed_then_n2_information_available_event_is_not_emitted(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
        )
        state_in = scenario.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        self.ctx.run(self.ctx.on.relation_changed(fiveg_n2_relation), state_in)

        assert len(self.ctx.emitted_events) == 1

    def test_given_invalid_n2_information_in_relation_data_when_relation_changed_then_n2_information_available_event_is_not_emitted(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
            remote_app_data={
                "amf_ip_address": "1.2.3.4",
                "amf_hostname": "amf",
                "amf_port": "invalid_port123",
            },
        )
        state_in = scenario.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        self.ctx.run(self.ctx.on.relation_changed(fiveg_n2_relation), state_in)

        assert len(self.ctx.emitted_events) == 1

    def test_given_n2_information_in_relation_data_when_get_n2_information_is_called_then_information_is_returned(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(
            endpoint="fiveg-n2",
            interface="fiveg_n2",
            remote_app_data={
                "amf_ip_address": "1.2.3.4",
                "amf_hostname": "amf",
                "amf_port": "38412",
            },
        )
        state_in = scenario.State(
            leader=True,
            relations={fiveg_n2_relation},
        )

        self.ctx.run(self.ctx.on.action("get-n2-information"), state_in)

        assert self.ctx.action_results
        assert self.ctx.action_results == {
            "amf-ip-address": "1.2.3.4",
            "amf-hostname": "amf",
            "amf-port": "38412",
        }
