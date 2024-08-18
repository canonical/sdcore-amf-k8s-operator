# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from unittest.mock import PropertyMock, patch

import pytest
import scenario
from ops.pebble import Layer, ServiceStatus

from charm import AMFOperatorCharm
from k8s_service import K8sService
from lib.charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateSigningRequest,
    PrivateKey,
    ProviderCertificate,
)
from tests.unit.certificates_helpers import (
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)

NRF_URL = "http://nrf:8081"
WEBUI_URL = "sdcore-webui:9876"
DATABASE_LIB_PATH = "charms.data_platform_libs.v0.data_interfaces.DatabaseRequires"


class TestCharmFiveGN2RelationJoined:
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

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=AMFOperatorCharm,
        )

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_get_assigned_certificate = (
            TestCharmFiveGN2RelationJoined.patcher_get_assigned_certificate.start()
        )
        self.mock_is_resource_created = (
            TestCharmFiveGN2RelationJoined.patcher_is_resource_created.start()
        )
        self.mock_nrf_url = TestCharmFiveGN2RelationJoined.patcher_nrf_url.start()
        self.mock_webui_url = TestCharmFiveGN2RelationJoined.patcher_webui_url.start()
        self.mock_check_output = TestCharmFiveGN2RelationJoined.patcher_check_output.start()
        self.mock_k8s_service = (
            TestCharmFiveGN2RelationJoined.patcher_k8s_service.start().return_value
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

    def example_cert_and_key(self, tls_relation_id: int) -> tuple[ProviderCertificate, PrivateKey]:
        private_key_str = generate_private_key()
        csr = generate_csr(
            private_key=private_key_str,
            common_name="amf",
        )
        ca_private_key = generate_private_key()
        ca_certificate = generate_ca(
            private_key=ca_private_key,
            common_name="ca.com",
            validity=365,
        )
        certificate_str = generate_certificate(
            csr=csr,
            ca=ca_certificate,
            ca_key=ca_private_key,
            validity=365,
        )
        provider_certificate = ProviderCertificate(
            relation_id=tls_relation_id,
            certificate=Certificate.from_string(certificate_str),
            certificate_signing_request=CertificateSigningRequest.from_string(csr),
            ca=Certificate.from_string(ca_certificate),
            chain=[Certificate.from_string(ca_certificate)],
        )
        private_key = PrivateKey.from_string(private_key_str)
        return provider_certificate, private_key

    @patch(f"{DATABASE_LIB_PATH}.fetch_relation_data")
    def test_given_relations_created_and_database_available_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self, mock_fetch_relation_data
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            mock_fetch_relation_data.return_value = {
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
            provider_certificate, private_key = self.example_cert_and_key(
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

    @patch(f"{DATABASE_LIB_PATH}.fetch_relation_data")
    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self, mock_fetch_relation_data
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            mock_fetch_relation_data.return_value = {
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
            provider_certificate, private_key = self.example_cert_and_key(
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

    @patch(f"{DATABASE_LIB_PATH}.fetch_relation_data")
    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
        mock_fetch_relation_data,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            database_relation = scenario.Relation(endpoint="database", interface="mongodb_client")
            mock_fetch_relation_data.return_value = {
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
            provider_certificate, private_key = self.example_cert_and_key(
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

    def test_given_service_not_running_when_fiveg_n2_relation_joined_then_n2_information_is_not_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
        container = scenario.Container(name="amf", can_connect=True)
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[fiveg_n2_relation],
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"

        state_out = self.ctx.run(fiveg_n2_relation.joined_event, state_in)

        assert state_out.relations[0].local_app_data == {}

    def test_given_n2_information_and_service_is_running_when_fiveg_n2_relation_joined_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
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
        )
        state_in = scenario.State(
            leader=True,
            containers=[container],
            relations=[
                fiveg_n2_relation,
            ],
        )
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"

        state_out = self.ctx.run(fiveg_n2_relation.joined_event, state_in)

        assert state_out.relations[0].local_app_data == {
            "amf_ip_address": "1.1.1.1",
            "amf_hostname": "amf.pizza.com",
            "amf_port": "38412",
        }

    def test_given_n2_information_and_service_is_running_and_n2_config_is_overriden_when_fiveg_n2_relation_joined_then_custom_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        fiveg_n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
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
        )
        state_in = scenario.State(
            config={"external-amf-ip": "2.2.2.2", "external-amf-hostname": "amf.burger.com"},
            leader=True,
            containers=[container],
            relations=[
                fiveg_n2_relation,
            ],
        )
        self.mock_k8s_service.get_hostname.return_value = "amf.pizza.com"
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"

        state_out = self.ctx.run(fiveg_n2_relation.joined_event, state_in)

        assert state_out.relations[0].local_app_data == {
            "amf_ip_address": "2.2.2.2",
            "amf_hostname": "amf.burger.com",
            "amf_port": "38412",
        }

    def test_given_n2_information_and_service_is_running_and_lb_service_has_no_hostname_when_fiveg_n2_relation_joined_then_internal_service_hostname_is_used(  # noqa: E501
        self,
    ):
        model_name = "whatever"
        fiveg_n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
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
        )
        state_in = scenario.State(
            model=scenario.Model(
                name=model_name,
            ),
            config={"external-amf-ip": "2.2.2.2"},
            leader=True,
            containers=[container],
            relations=[
                fiveg_n2_relation,
            ],
        )
        self.mock_check_output.return_value = b"1.1.1.1"
        self.mock_k8s_service.get_hostname.return_value = None
        self.mock_k8s_service.get_ip.return_value = "1.1.1.1"
        self.mock_is_resource_created.return_value = True
        self.mock_nrf_url.return_value = NRF_URL

        state_out = self.ctx.run(fiveg_n2_relation.joined_event, state_in)

        assert state_out.relations[0].local_app_data == {
            "amf_ip_address": "2.2.2.2",
            "amf_hostname": f"sdcore-amf-k8s-external.{model_name}.svc.cluster.local",
            "amf_port": "38412",
        }
