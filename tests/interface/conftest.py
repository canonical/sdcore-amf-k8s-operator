import tempfile
from unittest.mock import patch

import pytest
import scenario
from interface_tester import InterfaceTester
from ops.pebble import Layer, ServiceStatus

from charm import AMFOperatorCharm


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):

    with tempfile.TemporaryDirectory() as tempdir:
        with patch("charm.K8sService"):
            database_relation = scenario.Relation(
                endpoint="database",
                interface="mongodb_client",
                remote_app_data={
                    "username": "banana",
                    "password": "pizza",
                    "uris": "1.1.1.1:1234",
                },
            )
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )

            certs_mount = scenario.Mount(
                location="/support/TLS",
                src=tempdir,
            )
            config_mount = scenario.Mount(
                location="/free5gc/config",
                src=tempdir,
            )
            container = scenario.Container(
                name="amf",
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
                                        "POD_IP": "1.1.1.1",
                                        "MANAGED_BY_CONFIG_POD": "true",
                                    },
                                }
                            }
                        }
                    )
                },
                can_connect=True,
                mounts={"certs": certs_mount, "config": config_mount},
                service_status={"amf": ServiceStatus.ACTIVE},
            )

            interface_tester.configure(
                charm_type=AMFOperatorCharm,
                state_template=scenario.State(
                    leader=True,
                    relations=[database_relation, certificates_relation],
                    containers=[container],
                ),
            )
            yield interface_tester
