# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile

import scenario

from tests.unit.certificates_helpers import (
    example_cert_and_key,
)
from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmCertificatesRelationBroken(AMFUnitTestFixtures):
    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            certificates_relation = scenario.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            provider_certificate, private_key = example_cert_and_key(
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