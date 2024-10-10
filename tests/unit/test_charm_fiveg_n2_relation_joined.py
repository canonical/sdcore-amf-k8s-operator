# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from ops import testing
from ops.pebble import Layer, ServiceStatus

from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmFiveGN2RelationJoined(AMFUnitTestFixtures):
    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
        container = testing.Container(name="amf", can_connect=True)
        state_in = testing.State(
            leader=True,
            containers={container},
            relations={fiveg_n2_relation},
        )
        self.mock_check_output.return_value = b"192.0.2.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.example.com"
        self.mock_k8s_service.get_ip.return_value = "192.0.2.1"

        state_out = self.ctx.run(self.ctx.on.relation_joined(fiveg_n2_relation), state_in)

        assert state_out.get_relation(fiveg_n2_relation.id).local_app_data == {}

    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
        container = testing.Container(
            name="amf",
            can_connect=True,
            layers={
                "amf": Layer(
                    {
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
                                    "POD_IP": "192.0.2.1",
                                    "MANAGED_BY_CONFIG_POD": "true",
                                },
                            }
                        }
                    }
                )
            },
            service_statuses={"amf": ServiceStatus.ACTIVE},
        )
        state_in = testing.State(
            leader=True,
            containers={container},
            relations={
                fiveg_n2_relation,
            },
        )
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.example.com"
        self.mock_k8s_service.get_ip.return_value = "192.0.2.1"

        state_out = self.ctx.run(self.ctx.on.relation_joined(fiveg_n2_relation), state_in)

        assert state_out.get_relation(fiveg_n2_relation.id).local_app_data == {
            "amf_ip_address": "192.0.2.1",
            "amf_hostname": "amf.pizza.example.com",
            "amf_port": "38412",
        }

    def test_given_n2_information_and_service_is_running_and_n2_config_is_overriden_when_fiveg_n2_relation_joined_then_custom_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
        container = testing.Container(
            name="amf",
            can_connect=True,
            layers={
                "amf": Layer(
                    {
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
                                    "POD_IP": "192.0.2.1",
                                    "MANAGED_BY_CONFIG_POD": "true",
                                },
                            }
                        }
                    }
                )
            },
            service_statuses={"amf": ServiceStatus.ACTIVE},
        )
        state_in = testing.State(
            config={
                "external-amf-ip": "192.0.2.2",
                "external-amf-hostname": "amf.burger.example.com",
            },
            leader=True,
            containers={container},
            relations={
                fiveg_n2_relation,
            },
        )
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.example.com"
        self.mock_k8s_service.get_ip.return_value = "192.0.2.1"

        state_out = self.ctx.run(self.ctx.on.relation_joined(fiveg_n2_relation), state_in)

        assert state_out.get_relation(fiveg_n2_relation.id).local_app_data == {
            "amf_ip_address": "192.0.2.2",
            "amf_hostname": "amf.burger.example.com",
            "amf_port": "38412",
        }

    def test_given_n2_information_and_service_is_running_and_lb_service_has_no_hostname_when_fiveg_n2_relation_joined_then_internal_service_hostname_is_used(  # noqa: E501
        self,
    ):
        model_name = "whatever"
        fiveg_n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
        container = testing.Container(
            name="amf",
            can_connect=True,
            layers={
                "amf": Layer(
                    {
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
                                    "POD_IP": "192.0.2.1",
                                    "MANAGED_BY_CONFIG_POD": "true",
                                },
                            }
                        }
                    }
                )
            },
            service_statuses={"amf": ServiceStatus.ACTIVE},
        )
        state_in = testing.State(
            model=testing.Model(
                name=model_name,
            ),
            config={"external-amf-ip": "192.0.2.2"},
            leader=True,
            containers={container},
            relations={
                fiveg_n2_relation,
            },
        )
        self.mock_check_output.return_value = b"192.0.2.1"
        self.mock_k8s_service.get_hostname.return_value = None
        self.mock_k8s_service.get_ip.return_value = "192.0.2.1"
        self.mock_nrf_url.return_value = "http://nrf:8081"

        state_out = self.ctx.run(self.ctx.on.relation_joined(fiveg_n2_relation), state_in)

        assert state_out.get_relation(fiveg_n2_relation.id).local_app_data == {
            "amf_ip_address": "192.0.2.2",
            "amf_hostname": f"sdcore-amf-k8s-external.{model_name}.svc.cluster.local",
            "amf_port": "38412",
        }
