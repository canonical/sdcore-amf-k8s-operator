# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
from unittest.mock import PropertyMock, patch

import pytest
import scenario
from ops import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Layer, ServiceStatus

from charm import AMFOperatorCharm
from k8s_service import K8sService
from tests.unit.certificates_helpers import (
    example_cert_and_key,
)

NRF_URL = "http://nrf:8081"
WEBUI_URL = "sdcore-webui:9876"
DATABASE_LIB_PATH = "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires"


class TestCharmCollectUnitStatus:
    patcher_check_output = patch("charm.check_output")
    patcher_k8s_service = patch("charm.K8sService", autospec=K8sService)
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
    def context(self):
        self.ctx = scenario.Context(
            charm_type=AMFOperatorCharm,
        )

    @pytest.fixture(autouse=True)
    def setup(self, request):
        self.mock_get_assigned_certificate = (
            TestCharmCollectUnitStatus.patcher_get_assigned_certificate.start()
        )
        self.mock_is_resource_created = (
            TestCharmCollectUnitStatus.patcher_is_resource_created.start()
        )
        self.mock_nrf_url = TestCharmCollectUnitStatus.patcher_nrf_url.start()
        self.mock_webui_url = TestCharmCollectUnitStatus.patcher_webui_url.start()
        self.mock_check_output = TestCharmCollectUnitStatus.patcher_check_output.start()
        self.mock_k8s_service = TestCharmCollectUnitStatus.patcher_k8s_service.start().return_value
        self.mock_db_fetch_relation_data = (
            TestCharmCollectUnitStatus.patcher_db_fetch_relation_data.start()
        )
        yield
        request.addfinalizer(self.teardown)

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    def test_given_fiveg_nrf_relation_not_created_when_collect_unit_status_then_status_is_blocked(
        self,
    ):
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[certificates_relation, database_relation, sdcore_config_relation],
        )

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == BlockedStatus("Waiting for fiveg_nrf relation(s)")

    def test_given_database_relation_not_created_when_collect_unit_status_then_status_is_blocked(
        self,
    ):
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[nrf_relation, sdcore_config_relation, certificates_relation],
        )

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == BlockedStatus("Waiting for database relation(s)")

    def test_given_certificates_relation_not_created_when_collect_unit_status_then_status_is_blocked(  # noqa: E501
        self,
    ):
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[nrf_relation, database_relation, sdcore_config_relation],
        )

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == BlockedStatus("Waiting for certificates relation(s)")

    def test_given_sdcore_config_relation_not_created_when_collect_unit_status_then_status_is_blocked(  # noqa: E501
        self,
    ):
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[database_relation, nrf_relation, certificates_relation],
        )

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == BlockedStatus("Waiting for sdcore_config relation(s)")

    def test_given_relations_created_and_database_not_available_when_collect_unit_status_then_status_is_waiting(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {database_relation.relation_id: None}
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
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
                                        "POD_IP": "1.1.1.1",
                                        "MANAGED_BY_CONFIG_POD": "true",
                                    },
                                }
                            }
                        }
                    )
                },
                service_status={"amf": ServiceStatus.ACTIVE},
                mounts={"certs": certs_mount, "config": config_mount},
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    nrf_relation,
                    database_relation,
                    certificates_relation,
                    sdcore_config_relation,
                ],
            )
            self.mock_check_output.return_value = b"1.1.1.1"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.unit_status == WaitingStatus(
                "Waiting for AMF database info to be available"
            )

    def test_given_nrf_data_not_available_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        self.mock_db_fetch_relation_data.return_value = {
            database_relation.relation_id: {"uris": "abc.com"}
        }
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[
                database_relation,
                certificates_relation,
                sdcore_config_relation,
                nrf_relation,
            ],
        )
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = ""

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for NRF data to be available")

    def test_given_webui_data_not_available_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        self.mock_db_fetch_relation_data.return_value = {
            database_relation.relation_id: {"uris": "abc.com"}
        }
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[
                database_relation,
                nrf_relation,
                certificates_relation,
                sdcore_config_relation,
            ],
        )
        self.mock_is_resource_created.return_value = True
        self.mock_webui_url.return_value = ""
        self.mock_nrf_url.return_value = NRF_URL

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for Webui data to be available")

    def test_given_storage_not_attached_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
        self.mock_db_fetch_relation_data.return_value = {
            database_relation.relation_id: {"uris": "abc.com"}
        }
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[
                database_relation,
                nrf_relation,
                certificates_relation,
                sdcore_config_relation,
            ],
        )
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for storage to be attached")

    def test_given_certificates_not_stored_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "abc.com"}
            }
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            config_mount = scenario.Mount(
                location="/free5gc/config",
                src=tempdir,
            )
            container = scenario.Container(
                name="amf", can_connect=True, mounts={"config": config_mount}
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                ],
            )
            self.mock_get_assigned_certificate.return_value = None, None
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.unit_status == WaitingStatus(
                "Waiting for certificates to be available"
            )

    def test_relations_available_and_config_pushed_and_pebble_updated_when_collect_unit_status_then_status_is_active(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "abc.com"}
            }
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
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
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                ],
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.unit_status == ActiveStatus()

    def test_given_empty_ip_address_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "abc.com"}
            }
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
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
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                ],
            )
            self.mock_check_output.return_value = b""
            self.mock_nrf_url.return_value = NRF_URL

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.unit_status == WaitingStatus(
                "Waiting for pod IP address to be available"
            )

    def test_given_no_workload_version_file_when_collect_unit_status_then_workload_version_not_set(
        self,
    ):
        nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
        certificates_relation = scenario.Relation(
            endpoint="certificates", interface="tls-certificates"
        )
        sdcore_config_relation = scenario.Relation(
            endpoint="sdcore_config", interface="sdcore_config"
        )
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[nrf_relation, certificates_relation, sdcore_config_relation],
        )

        state_out = self.ctx.run("collect_unit_status", state_in)

        assert state_out.workload_version == ""

    def test_given_workload_version_file_when_collect_unit_status_then_workload_version_set(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            workload_version_mount = scenario.Mount(
                location="/etc",
                src=tempdir,
            )
            # Write workload version file
            expected_version = "1.2.3"
            with open(f"{tempdir}/workload-version", "w") as f:
                f.write(expected_version)
            container = scenario.Container(
                name="amf", can_connect=True, mounts={"workload-version": workload_version_mount}
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[nrf_relation, certificates_relation, sdcore_config_relation],
            )

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.workload_version == expected_version

    def test_given_n2_information_and_service_is_running_and_metallb_service_is_not_available_when_collect_unit_status_then_amf_goes_in_blocked_state(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "abc.com"}
            }
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            fiveg_n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
            config_mount = scenario.Mount(
                location="/free5gc/config",
                src=tempdir,
            )
            certs_mount = scenario.Mount(
                location="/support/TLS",
                src=tempdir,
            )
            container = scenario.Container(
                name="amf",
                can_connect=True,
                mounts={"certs": certs_mount, "config": config_mount},
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
                service_status={"amf": ServiceStatus.ACTIVE},
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    fiveg_n2_relation,
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                ],
            )
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_k8s_service.get_hostname.return_value = None
            self.mock_k8s_service.get_ip.return_value = None
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL

            state_out = self.ctx.run("collect_unit_status", state_in)

            assert state_out.unit_status == BlockedStatus("Waiting for MetalLB to be enabled")
