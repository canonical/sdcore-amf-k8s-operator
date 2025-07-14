#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""K8sService class to manage external AMF service."""

import logging
from typing import Optional

from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service

logger = logging.getLogger(__name__)


class K8sService:
    """K8sService class to manage external AMF service."""

    def __init__(
            self,
            namespace: str,
            service_name: str,
            service_port: int,
            app_name: str,
            unit_id: str
    ):
        self.namespace = namespace
        self.service_name = service_name
        self.service_port = service_port
        self.app_name = app_name
        self.unit_id = unit_id
        self.client = Client()

    def create(self) -> None:
        """Create the external AMF service."""
        self.client.apply(
            Service(
                apiVersion="v1",
                kind="Service",
                metadata=ObjectMeta(
                    namespace=self.namespace,
                    name=self.service_name,
                ),
                spec=ServiceSpec(
                    selector={"app.kubernetes.io/name": self.app_name},
                    ports=[
                        ServicePort(name="ngapp", port=self.service_port, protocol="SCTP"),
                    ],
                    type="LoadBalancer",
                ),
            ),
            field_manager=self.app_name,
        )
        logger.info("Created/asserted existence of external AMF service")

    def patch(self) -> None:
        """Patch the existing external AMF service with the pod index of the new leader."""
        self.client.patch(
            res=Service,
            name=self.service_name,
            namespace=self.namespace,
            field_manager=self.app_name,
            obj=Service(
                spec=ServiceSpec(
                    selector={
                        "apps.kubernetes.io/pod-index": self.unit_id,
                    },
                )
            )
        )

    def is_created(self) -> bool:
        """Check if the external AMF service is created."""
        try:
            self.client.get(Service, name=self.service_name, namespace=self.namespace)
            return True
        except Exception:
            return False

    def requires_patch(self) -> bool:
        """Check if the external AMF service requires patching."""
        try:
            service = self.client.get(Service, name=self.service_name, namespace=self.namespace)
            if not service.spec:
                logger.debug("Service `%s` not found", self.service_name)
                return False
            if not service.spec.selector:
                return True
            if service.spec.selector.get("apps.kubernetes.io/pod-index") != self.unit_id:
                return True
            return False
        except Exception:
            return False

    def remove(self):
        """Remove the external AMF service."""
        client = Client()
        client.delete(
            Service,
            namespace=self.namespace,
            name=self.service_name,
        )
        logger.info("Removed external AMF service")

    def get_ip(self) -> Optional[str]:
        """Return the external service IP."""
        try:
            service = self.client.get(Service, name=self.service_name, namespace=self.namespace)
        except ApiError:
            return None
        if not service.status:
            return None
        if not service.status.loadBalancer:
            return None
        if not service.status.loadBalancer.ingress:
            return None
        return service.status.loadBalancer.ingress[0].ip

    def get_hostname(self) -> Optional[str]:
        """Return the external service hostname."""
        try:
            service = self.client.get(Service, name=self.service_name, namespace=self.namespace)
        except ApiError:
            return None
        if not service.status:
            return None
        if not service.status.loadBalancer:
            return None
        if not service.status.loadBalancer.ingress:
            return None
        return service.status.loadBalancer.ingress[0].hostname
