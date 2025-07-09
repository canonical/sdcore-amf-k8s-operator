# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import ops.pebble
from ops import testing
from ops.pebble import Layer

from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmConfigure(AMFUnitTestFixtures):
    def test_given_replicas_relation_created_and_unit_is_leader_when_leader_elected_then_databag_is_updated(  #noqa E501
        self,
    ):
        replicas_relation = testing.PeerRelation(
            endpoint="replicas",
        )
        container = testing.Container(
            name="amf", can_connect=True
        )
        state_in = testing.State(
            leader=True,
            containers={container},
            relations={
                replicas_relation,
            },
        )
        state_out = self.ctx.run(self.ctx.on.leader_elected(), state_in)
        relation_data = state_out.get_relation(replicas_relation.id).local_app_data
        assert relation_data.get("leader") is not None
        assert relation_data.get("elected-at") is not None

    def test_given_replicas_relation_created_and_unit_is_not_leader_when_replicas_relation_changed_then_databag_is_not_updated(  # noqa E501
        self,
    ):
        replicas_relation = testing.PeerRelation(
            endpoint="replicas",
        )
        container = testing.Container(
            name="amf", can_connect=True
        )
        state_in = testing.State(
            leader=False,
            containers={container},
            relations={
                replicas_relation,
            },
        )
        state_out = self.ctx.run(self.ctx.on.relation_changed(replicas_relation), state_in)
        relation_data = state_out.get_relation(replicas_relation.id).local_app_data
        assert relation_data.get("leader") is None
        assert relation_data.get("elected-at") is None

    def test_given_replicas_relation_created_and_unit_is_not_leader_when_replicas_relation_changed_then_amf_is_stopped(  # noqa E501
        self,
    ):
        replicas_relation = testing.PeerRelation(
            endpoint="replicas",
        )
        container = testing.Container(
            name="amf", can_connect=True,
            layers={
                "amf": Layer(
                    {
                        "services": {
                            "amf": {
                                "startup": "enabled",
                                "override": "replace",
                                "command": "/bin/amf --cfg /free5gc/config/amfcfg.conf",
                                "environment": {
                                    "GOTRACEBACK": "crash",
                                    "POD_IP": "192.0.2.1",
                                    "MANAGED_BY_CONFIG_POD": "true",
                                },
                            }
                        }
                    }
                )
            },
            service_statuses={"amf": ops.pebble.ServiceStatus.ACTIVE},
        )
        state_in = testing.State(
            leader=False,
            containers={container},
            relations={
                replicas_relation,
            },
        )
        self.ctx.run(self.ctx.on.relation_changed(replicas_relation), state_in)
        self.mock_stop.assert_called_once()
