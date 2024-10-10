# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile

from ops import testing

from tests.unit.certificates_helpers import (
    example_cert_and_key,
)
from tests.unit.fixtures import AMFUnitTestFixtures


class TestCharmCertificatesRelationBroken(AMFUnitTestFixtures):
    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            certificates_relation = testing.Relation(
                endpoint="certificates", interface="tls-certificates"
            )
            provider_certificate, private_key = example_cert_and_key(
                tls_relation_id=certificates_relation.id
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

            state_in = testing.State(
                relations={certificates_relation},
                containers={container},
                leader=True,
            )

            self.ctx.run(self.ctx.on.relation_broken(certificates_relation), state_in)

            assert not os.path.exists(f"{tempdir}/amf.pem")
            assert not os.path.exists(f"{tempdir}/amf.key")
