# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import scenario

from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmRemove(AMFUnitTestFixtures):
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