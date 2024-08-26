# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import pytest
import scenario

from charm import AMFOperatorCharm
from k8s_service import K8sService


class AMFUnitTestFixtures:
    patcher_k8s_service = patch("charm.K8sService", autospec=K8sService)
    patcher_check_output = patch("charm.check_output")
    patcher_nrf_url = patch(
        "charms.sdcore_nrf_k8s.v0.fiveg_nrf.NRFRequires.nrf_url", new_callable=PropertyMock
    )
    patcher_webui_url = patch(
        "charms.sdcore_nms_k8s.v0.sdcore_config.SdcoreConfigRequires.webui_url",
        new_callable=PropertyMock,
    )
    patcher_is_resource_created = patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created"
    )
    patcher_get_assigned_certificate = patch(
        "charms.tls_certificates_interface.v4.tls_certificates.TLSCertificatesRequiresV4.get_assigned_certificate"
    )
    patcher_db_fetch_relation_data = patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.fetch_relation_data"
    )

    @pytest.fixture(autouse=True)
    def setup(self, request):
        self.mock_k8s_service = AMFUnitTestFixtures.patcher_k8s_service.start().return_value
        self.mock_get_assigned_certificate = (
            AMFUnitTestFixtures.patcher_get_assigned_certificate.start()
        )
        self.mock_is_resource_created = AMFUnitTestFixtures.patcher_is_resource_created.start()
        self.mock_nrf_url = AMFUnitTestFixtures.patcher_nrf_url.start()
        self.mock_webui_url = AMFUnitTestFixtures.patcher_webui_url.start()
        self.mock_check_output = AMFUnitTestFixtures.patcher_check_output.start()
        self.mock_db_fetch_relation_data = (
            AMFUnitTestFixtures.patcher_db_fetch_relation_data.start()
        )
        yield
        request.addfinalizer(self.teardown)

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=AMFOperatorCharm,
        )