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
                layers={"amf": Layer({"services": {"amf": {}}})},
                can_connect=True,
                mounts={"certs": certs_mount, "config": config_mount},
                service_status={"amf": ServiceStatus.ACTIVE},
            )

            interface_tester.configure(
                charm_type=AMFOperatorCharm,
                state_template=scenario.State(
                    leader=True,
                    containers=[container],
                ),
            )
            yield interface_tester
