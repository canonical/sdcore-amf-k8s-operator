#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
DB_CHARM_NAME = "mongodb-k8s"
NRF_CHARM_NAME = "sdcore-nrf"
TLS_PROVIDER_CHARM_NAME = "self-signed-certificates"


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it."""
    charm = await ops_test.build_charm(".")
    resources = {
        "amf-image": METADATA["resources"]["amf-image"]["upstream-source"],
    }
    await ops_test.model.deploy(  # type: ignore[union-attr]
        charm,
        resources=resources,
        application_name=APP_NAME,
        trust=True,
    )
    await ops_test.model.deploy(  # type: ignore[union-attr]
        DB_CHARM_NAME,
        application_name=DB_CHARM_NAME,
        channel="5/edge",
        trust=True,
    )
    await ops_test.model.deploy(  # type: ignore[union-attr]
        NRF_CHARM_NAME,
        application_name=NRF_CHARM_NAME,
        channel="edge",
        trust=True,
    )
    await ops_test.model.deploy(  # type: ignore[union-attr]
        TLS_PROVIDER_CHARM_NAME, application_name=TLS_PROVIDER_CHARM_NAME, channel="beta"
    )


@pytest.mark.abort_on_fail
async def test_deploy_charm_and_wait_for_blocked_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.wait_for_idle(  # type: ignore[union-attr]
        apps=[APP_NAME],
        status="blocked",
        timeout=1000,
    )


@pytest.mark.abort_on_fail
async def test_relate_and_wait_for_active_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.add_relation(  # type: ignore[union-attr]
        relation1=f"{NRF_CHARM_NAME}:database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.add_relation(  # type: ignore[union-attr]
        relation1=NRF_CHARM_NAME, relation2=TLS_PROVIDER_CHARM_NAME
    )
    await ops_test.model.add_relation(  # type: ignore[union-attr]
        relation1=f"{APP_NAME}:database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.add_relation(relation1=APP_NAME, relation2=NRF_CHARM_NAME)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.add_relation(relation1=APP_NAME, relation2=TLS_PROVIDER_CHARM_NAME)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.wait_for_idle(  # type: ignore[union-attr]
        apps=[APP_NAME],
        status="active",
        timeout=1000,
    )


@pytest.mark.abort_on_fail
async def test_remove_nrf_and_wait_for_blocked_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.remove_application(NRF_CHARM_NAME, block_until_done=True)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=60)  # type: ignore[union-attr]  # noqa: E501


@pytest.mark.abort_on_fail
async def test_restore_nrf_and_wait_for_active_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.deploy(  # type: ignore[union-attr]
        NRF_CHARM_NAME,
        application_name=NRF_CHARM_NAME,
        channel="edge",
        trust=True,
    )
    await ops_test.model.add_relation(  # type: ignore[union-attr]
        relation1=f"{NRF_CHARM_NAME}:database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.add_relation(relation1=NRF_CHARM_NAME, relation2=TLS_PROVIDER_CHARM_NAME)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.add_relation(relation1=APP_NAME, relation2=NRF_CHARM_NAME)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)  # type: ignore[union-attr]  # noqa: E501


@pytest.mark.abort_on_fail
async def test_remove_tls_and_wait_for_blocked_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.remove_application(TLS_PROVIDER_CHARM_NAME, block_until_done=True)  # type: ignore[union-attr]  # noqa: E501
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=60)  # type: ignore[union-attr]  # noqa: E501


@pytest.mark.abort_on_fail
async def test_restore_tls_and_wait_for_active_status(ops_test: OpsTest, build_and_deploy):
    await ops_test.model.deploy(  # type: ignore[union-attr]
        TLS_PROVIDER_CHARM_NAME,
        application_name=TLS_PROVIDER_CHARM_NAME,
        channel="beta",
        trust=True,
    )
    await ops_test.model.add_relation(  # type: ignore[union-attr]
        relation1=APP_NAME, relation2=TLS_PROVIDER_CHARM_NAME
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)  # type: ignore[union-attr]  # noqa: E501
