#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.

import logging

from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.core_v1 import Service

logger = logging.getLogger(__name__)


class KubernetesError(Exception):
    pass


def get_loadbalancer_service_selector_pod_index(service_name, namespace) -> list[str]:
    """Return the value of the POD index selector of a given LoadBalancer service."""
    try:
        lightkube_client = Client()
        service = lightkube_client.get(Service, name=service_name, namespace=namespace)
    except ApiError as e:
        raise KubernetesError() from e

    if not (spec := getattr(service, "spec", None)):
        raise KubernetesError("Unable to get spec of service %s", service_name)
    if not (selector_spec := getattr(spec, "selector", None)):
        raise KubernetesError("Unable to get spec selector for service %s", service_name)
    return selector_spec.get("apps.kubernetes.io/pod-index")
