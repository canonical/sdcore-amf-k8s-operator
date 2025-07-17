# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from ops import testing

from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmRemove(AMFUnitTestFixtures):
    def test_given_unit_is_leader_and_k8s_service_created_when_remove_then_external_service_is_deleted(  # noqa E501
        self,
    ):
        container = testing.Container(
            name="amf",
        )
        state_in = testing.State(
            leader=True,
            containers={container},
        )
        self.mock_k8s_service.is_created.return_value = True

        self.ctx.run(self.ctx.on.remove(), state_in)

        self.mock_k8s_service.remove.assert_called_once()

    def test_given_unit_is_not_leader_and_k8s_service_created_when_remove_then_external_service_is_not_deleted(  # noqa E501
        self,
    ):
        container = testing.Container(
            name="amf",
        )
        state_in = testing.State(
            leader=False,
            containers={container},
        )
        self.mock_k8s_service.is_created.return_value = True

        self.ctx.run(self.ctx.on.remove(), state_in)

        self.mock_k8s_service.remove.assert_not_called()
