# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from unittest.mock import patch

import pytest
import scenario

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


class TestCharmCertificatesRelationBroken:
    patcher_k8s_service = patch("charm.K8sService", autospec=K8sService)

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=AMFOperatorCharm,
        )

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_k8s_service = (
            TestCharmCertificatesRelationBroken.patcher_k8s_service.start().return_value
        )

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

    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            provider_certificate, private_key = self.example_cert_and_key(
                tls_relation_id=certificates_relation.relation_id
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
                mounts={"certs": certs_mount, "config": config_mount},
            )
            os.mkdir(f"{tempdir}/support")
            os.mkdir(f"{tempdir}/support/TLS")
            with open(f"{tempdir}/amf.pem", "w") as f:
                f.write(str(provider_certificate.certificate))

            with open(f"{tempdir}/amf.key", "w") as f:
                f.write(str(private_key))

            state_in = scenario.State(
                relations=[certificates_relation],
                containers=[container],
                leader=True,
            )

            self.ctx.run(certificates_relation.broken_event, state_in)

            assert not os.path.exists(f"{tempdir}/amf.pem")
            assert not os.path.exists(f"{tempdir}/amf.key")
