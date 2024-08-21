# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
import scenario

from charm import AMFOperatorCharm
from k8s_service import K8sService


class TestCharmRemove:
    patcher_k8s_service = patch("charm.K8sService", autospec=K8sService)

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=AMFOperatorCharm,
        )

    @pytest.fixture(autouse=True)
    def setup(self, request):
        self.mock_k8s_service = TestCharmRemove.patcher_k8s_service.start().return_value
        yield
        request.addfinalizer(self.teardown)

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    def test_given_k8s_service_created_when_remove_then_external_service_is_deleted(self):
        container = scenario.Container(
            name="amf",
        )
        state_in = scenario.State(
            leader=True,
            containers=[container],
        )
        self.mock_k8s_service.is_created.return_value = True

        self.ctx.run("remove", state_in)

        self.mock_k8s_service.remove.assert_called_once()
