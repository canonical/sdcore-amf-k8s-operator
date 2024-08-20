# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from unittest.mock import PropertyMock, patch

import pytest
import scenario
from ops.pebble import Layer

from charm import AMFOperatorCharm
from k8s_service import K8sService
from tests.unit.certificates_helpers import (
    example_cert_and_key,
)

NRF_URL = "http://nrf:8081"
WEBUI_URL = "sdcore-webui:9876"


class TestCharmConfigure:
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
    def setup(self):
        self.mock_get_assigned_certificate = (
            TestCharmConfigure.patcher_get_assigned_certificate.start()
        )
        self.mock_is_resource_created = TestCharmConfigure.patcher_is_resource_created.start()
        self.mock_nrf_url = TestCharmConfigure.patcher_nrf_url.start()
        self.mock_webui_url = TestCharmConfigure.patcher_webui_url.start()
        self.mock_check_output = TestCharmConfigure.patcher_check_output.start()
        self.mock_k8s_service = TestCharmConfigure.patcher_k8s_service.start().return_value
        self.mock_db_fetch_relation_data = (
            TestCharmConfigure.patcher_db_fetch_relation_data.start()
        )

    @staticmethod
    def _read_file(path: str) -> str:
        """Read a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content

    def test_given_relations_created_and_database_available_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
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
            self.mock_check_output.return_value = b"1.1.1.1"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL
            self.mock_webui_url.return_value = WEBUI_URL

            self.ctx.run(container.pebble_ready_event, state_in)

            with open(tempdir + "/amf.pem", "r") as f:
                assert f.read() == str(provider_certificate.certificate)

            with open(tempdir + "/amf.key", "r") as f:
                assert f.read() == str(private_key)

            with open(tempdir + "/amfcfg.conf", "r") as f:
                assert (
                    f.read().strip()
                    == self._read_file("tests/unit/expected_config/config.conf").strip()
                )

    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
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
            self.mock_check_output.return_value = b"1.1.1.1"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL
            self.mock_webui_url.return_value = WEBUI_URL

            with open(tempdir + "/amf.pem", "w") as f:
                f.write(str(provider_certificate.certificate))

            with open(tempdir + "/amf.key", "w") as f:
                f.write(str(private_key))

            with open(tempdir + "/amfcfg.conf", "w") as f:
                f.write(self._read_file("tests/unit/expected_config/config.conf").strip())

            config_modification_time = os.stat(tempdir + "/amfcfg.conf").st_mtime

            self.ctx.run(container.pebble_ready_event, state_in)

            assert os.stat(tempdir + "/amfcfg.conf").st_mtime == config_modification_time

    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
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
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL

            state_out = self.ctx.run(container.pebble_ready_event, state_in)

            assert state_out.containers[0].layers["amf"] == Layer(
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

    def test_given_service_starts_running_after_n2_relation_joined_when_pebble_ready_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
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
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                    fiveg_n2_relation,
                ],
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
            self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL
            self.mock_webui_url.return_value = WEBUI_URL

            state_out = self.ctx.run(container.pebble_ready_event, state_in)

            assert state_out.relations[4].local_app_data == {
                "amf_ip_address": "1.1.1.1",
                "amf_hostname": "amf.pizza.com",
                "amf_port": "38412",
            }

    def test_given_more_than_one_n2_requirers_join_n2_relation_when_service_starts_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
            }
            nrf_relation = scenario.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = scenario.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            fiveg_n2_relation_1 = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
            fiveg_n2_relation_2 = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
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
            )
            state_in = scenario.State(
                leader=True,
                containers=[container],
                relations=[
                    database_relation,
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                    fiveg_n2_relation_1,
                    fiveg_n2_relation_2,
                ],
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
            self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
            self.mock_is_resource_created.return_value = True
            self.mock_nrf_url.return_value = NRF_URL
            self.mock_webui_url.return_value = WEBUI_URL

            state_out = self.ctx.run(container.pebble_ready_event, state_in)

            assert state_out.relations[4].local_app_data == {
                "amf_ip_address": "1.1.1.1",
                "amf_hostname": "amf.pizza.com",
                "amf_port": "38412",
            }
            assert state_out.relations[5].local_app_data == {
                "amf_ip_address": "1.1.1.1",
                "amf_hostname": "amf.pizza.com",
                "amf_port": "38412",
            }

    def test_given_can_connect_when_on_pebble_ready_then_private_key_is_generated(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
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
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"1.1.1.1"

            self.ctx.run(container.pebble_ready_event, state_in)

            with open(tempdir + "/amf.key", "r") as f:
                assert f.read() == str(private_key)

    def test_given_certificate_matches_stored_one_when_pebble_ready_then_certificate_is_not_pushed(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            self.mock_db_fetch_relation_data.return_value = {
                database_relation.relation_id: {"uris": "http://dummy"}
            }
            container = scenario.Container(
                name="amf",
                can_connect=True,
                mounts={
                    "certs": scenario.Mount(
                        location="/support/TLS",
                        src=tempdir,
                    ),
                    "config": scenario.Mount(
                        location="/free5gc/config",
                        src=tempdir,
                    ),
                },
            )
            state_in = scenario.State(
                leader=True,
                relations=[database_relation],
                containers=[container],
            )
            self.mock_check_output.return_value = b"1.1.1.1"
            self.mock_nrf_url.return_value = NRF_URL
            provider_certificate, private_key = example_cert_and_key(tls_relation_id=1)
            with open(f"{tempdir}/amf.pem", "w") as f:
                f.write(str(provider_certificate.certificate))
            with open(f"{tempdir}/amf.key", "w") as f:
                f.write(str(private_key))

            self.ctx.run(container.pebble_ready_event, state_in)

            config_modification_time_amf_pem = os.stat(tempdir + "/amf.pem").st_mtime
            config_modification_time_amf_key = os.stat(tempdir + "/amf.key").st_mtime
            assert os.stat(tempdir + "/amf.pem").st_mtime == config_modification_time_amf_pem
            assert os.stat(tempdir + "/amf.key").st_mtime == config_modification_time_amf_key

    def test_given_k8s_service_not_created_when_pebble_ready_then_service_is_created(self):
        container = scenario.Container(
            name="amf",
        )
        state_in = scenario.State(
            leader=True,
            containers=[container],
        )
        self.mock_k8s_service.is_created.return_value = False

        self.ctx.run(container.pebble_ready_event, state_in)

        self.mock_k8s_service.create.assert_called_once()
