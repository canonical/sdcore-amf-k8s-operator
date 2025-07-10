# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile

from ops import testing
from ops.pebble import Layer

from tests.unit.certificates_helpers import (
    example_cert_and_key,
)
from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmConfigure(AMFUnitTestFixtures):
    def test_given_relations_created_and_nrf_data_available_and_certs_stored_when_pebble_ready_then_config_file_rendered_and_pushed_correctly(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            container = testing.Container(
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
            )
            self.mock_check_output.return_value = b"192.0.2.1"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_nrf_url.return_value = "http://nrf:8081"
            self.mock_webui_url.return_value = "sdcore-webui:9876"

            self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            with open(tempdir + "/amf.pem", "r") as f:
                assert f.read() == str(provider_certificate.certificate)

            with open(tempdir + "/amf.key", "r") as f:
                assert f.read() == str(private_key)

            with open(tempdir + "/amfcfg.conf", "r") as f:
                actual_config = f.read().strip()

            with open("tests/unit/expected_config/config.conf", "r") as f:
                expected_config = f.read().strip()

            assert actual_config == expected_config

    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            container = testing.Container(
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
            )
            self.mock_check_output.return_value = b"192.0.2.1"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_nrf_url.return_value = "http://nrf:8081"
            self.mock_webui_url.return_value = "sdcore-webui:9876"

            with open(tempdir + "/amf.pem", "w") as f:
                f.write(str(provider_certificate.certificate))

            with open(tempdir + "/amf.key", "w") as f:
                f.write(str(private_key))

            with open("tests/unit/expected_config/config.conf", "r") as f:
                expected_config = f.read()

            with open(tempdir + "/amfcfg.conf", "w") as f:
                f.write(expected_config.strip())

            config_modification_time = os.stat(tempdir + "/amfcfg.conf").st_mtime

            self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            with open(tempdir + "/amfcfg.conf", "r") as config_file:
                actual_config = config_file.read()

            with open("tests/unit/expected_config/config.conf", "r") as expected_config_file:
                expected_config = expected_config_file.read()

            assert actual_config.strip() == expected_config.strip()
            assert os.stat(tempdir + "/amfcfg.conf").st_mtime == config_modification_time

    def test_given_relations_available_and_config_pushed_when_pebble_ready_then_pebble_is_applied_correctly(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            container = testing.Container(
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"192.0.2.1"
            self.mock_nrf_url.return_value = "http://nrf:8081"

            state_out = self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            assert state_out.get_container("amf").layers["amf"] == Layer(
                {
                    "services": {
                        "amf": {
                            "startup": "enabled",
                            "override": "replace",
                            "command": "/bin/amf --cfg /free5gc/config/amfcfg.conf",
                            "environment": {
                                "GOTRACEBACK": "crash",
                                "POD_IP": "192.0.2.1",
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
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            fiveg_n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            container = testing.Container(
                name="amf",
                can_connect=True,
                mounts={"certs": certs_mount, "config": config_mount},
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                    fiveg_n2_relation,
                },
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"192.0.2.1"
            self.mock_k8s_service.get_ip.return_value = "192.0.2.1"
            self.mock_k8s_service.get_hostname.return_value = "amf.pizza.example.com"
            self.mock_nrf_url.return_value = "http://nrf:8081"
            self.mock_webui_url.return_value = "sdcore-webui:9876"

            state_out = self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            assert state_out.get_relation(fiveg_n2_relation.id).local_app_data == {
                "amf_ip_address": "192.0.2.1",
                "amf_hostname": "amf.pizza.example.com",
                "amf_port": "38412",
            }

    def test_given_more_than_one_n2_requirers_join_n2_relation_when_service_starts_then_n2_information_is_in_relation_databag(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            fiveg_n2_relation_1 = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
            fiveg_n2_relation_2 = testing.Relation(endpoint="fiveg-n2", interface="fiveg-n2")
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            container = testing.Container(
                name="amf",
                can_connect=True,
                mounts={"certs": certs_mount, "config": config_mount},
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                    fiveg_n2_relation_1,
                    fiveg_n2_relation_2,
                },
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"192.0.2.1"
            self.mock_k8s_service.get_ip.return_value = "192.0.2.1"
            self.mock_k8s_service.get_hostname.return_value = "amf.pizza.example.com"
            self.mock_nrf_url.return_value = "http://nrf:8081"
            self.mock_webui_url.return_value = "sdcore-webui:9876"

            state_out = self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            assert state_out.get_relation(fiveg_n2_relation_1.id).local_app_data == {
                "amf_ip_address": "192.0.2.1",
                "amf_hostname": "amf.pizza.example.com",
                "amf_port": "38412",
            }
            assert state_out.get_relation(fiveg_n2_relation_2.id).local_app_data == {
                "amf_ip_address": "192.0.2.1",
                "amf_hostname": "amf.pizza.example.com",
                "amf_port": "38412",
            }

    def test_given_can_connect_when_on_pebble_ready_then_private_key_is_generated(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            container = testing.Container(
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"192.0.2.1"

            self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            with open(tempdir + "/amf.key", "r") as f:
                assert f.read() == str(private_key)

    def test_given_certificate_matches_stored_one_when_pebble_ready_then_certificate_is_not_pushed(
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            container = testing.Container(
                name="amf",
                can_connect=True,
                mounts={
                    "certs": testing.Mount(
                        location="/support/TLS",
                        source=tempdir,
                    ),
                    "config": testing.Mount(
                        location="/free5gc/config",
                        source=tempdir,
                    ),
                },
            )
            state_in = testing.State(
                leader=True,
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
                containers={container},
            )
            self.mock_check_output.return_value = b"192.0.2.1"
            self.mock_nrf_url.return_value = "http://nrf:8081"
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            with open(f"{tempdir}/amf.pem", "w") as f:
                f.write(str(provider_certificate.certificate))
            with open(f"{tempdir}/amf.key", "w") as f:
                f.write(str(private_key))
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            config_modification_time_amf_pem = os.stat(tempdir + "/amf.pem").st_mtime
            config_modification_time_amf_key = os.stat(tempdir + "/amf.key").st_mtime

            self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

            assert os.stat(tempdir + "/amf.pem").st_mtime == config_modification_time_amf_pem
            assert os.stat(tempdir + "/amf.key").st_mtime == config_modification_time_amf_key

    def test_given_k8s_service_not_created_when_pebble_ready_then_service_is_created(self):
        container = testing.Container(
            name="amf",
        )
        state_in = testing.State(
            leader=True,
            containers={container},
        )
        self.mock_k8s_service.is_created.return_value = False

        self.ctx.run(self.ctx.on.pebble_ready(container), state_in)

        self.mock_k8s_service.create.assert_called_once()

    def test_given_k8s_service_created_when_leader_elected_then_service_is_patched(self):
        container = testing.Container(
            name="amf",
        )
        state_in = testing.State(
            leader=True,
            containers={container},
        )
        self.mock_k8s_service.is_created.return_value = True

        self.ctx.run(self.ctx.on.leader_elected(), state_in)

        self.mock_k8s_service.patch.assert_called_once()

    def test_given_unit_was_no_leader_when_leader_elected_then_pebble_is_applied_correctly(self):
        with tempfile.TemporaryDirectory() as tempdir:
            nrf_relation = testing.Relation(endpoint="fiveg_nrf", interface="fiveg_nrf")
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            sdcore_config_relation = testing.Relation(
                endpoint="sdcore_config", interface="sdcore_config"
            )
            certs_mount = testing.Mount(
                location="/support/TLS",
                source=tempdir,
            )
            config_mount = testing.Mount(
                location="/free5gc/config",
                source=tempdir,
            )
            container = testing.Container(
                name="amf", can_connect=True, mounts={"certs": certs_mount, "config": config_mount}
            )
            state_in = testing.State(
                leader=True,
                containers={container},
                relations={
                    nrf_relation,
                    certificates_relation,
                    sdcore_config_relation,
                },
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
            )
            self.mock_get_assigned_certificate.return_value = provider_certificate, private_key
            self.mock_check_output.return_value = b"192.0.2.1"
            self.mock_nrf_url.return_value = "http://nrf:8081"

            state_out = self.ctx.run(self.ctx.on.leader_elected(), state_in)

            assert state_out.get_container("amf").layers["amf"] == Layer(
                {
                    "services": {
                        "amf": {
                            "startup": "enabled",
                            "override": "replace",
                            "command": "/bin/amf --cfg /free5gc/config/amfcfg.conf",
                            "environment": {
                                "GOTRACEBACK": "crash",
                                "POD_IP": "192.0.2.1",
                                "MANAGED_BY_CONFIG_POD": "true",
                            },
                        }
                    }
                }
            )
