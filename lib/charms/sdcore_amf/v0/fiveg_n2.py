# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the `fiveg_n2` relation.

This library contains the Requires and Provides classes for handling the `fiveg_n2`
interface.

The purpose of this library is to relate a charm claiming 
to be able to provide or consume information on connectivity to the N2 plane.

## Getting Started
From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.sdcore_amf_operator.v0.fiveg_n2
```

Add the following libraries to the charm's `requirements.txt` file:
- pydantic
- pytest-interface-tester

### Requirer charm
The requirer charm is the one requiring the N2 information.

Example:
```python

from ops.charm import CharmBase
from ops.main import main

from charms.sdcore_n2.v0.fiveg_n2 import N2InformationAvailableEvent, N2Requires

logger = logging.getLogger(__name__)


class DummyFivegN2Requires(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_requirer = N2Requires(self, "fiveg-n2")
        self.framework.observe(self.n2_requirer.on.n2_information_available, self._on_n2_information_available)

    def _on_n2_information_available(self, event: N2InformationAvailableEvent):
        amf_hostname = event.amf_hostname
        ngapp_port = event.ngapp_port
        <do something with the amf hostname and port>


if __name__ == "__main__":
    main(DummyFivegN2Requires)
```

### Provider charm
The provider charm is the one providing the information about the N2 interface.

Example:
```python

from ops.charm import CharmBase, RelationJoinedEvent
from ops.main import main

from charms.sdcore_n2.v0.fiveg_n2 import N2Provides


class DummyFivegN2ProviderCharm(CharmBase):

    AMF_HOST = "amf"
    NGAPP_PORT = 38412

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_provider = N2Provides(self, "fiveg-n2")
        self.framework.observe(
            self.on.fiveg_n2_relation_joined, self._on_fiveg_n2_relation_joined
        )

    def _on_fiveg_n2_relation_joined(self, event: RelationJoinedEvent):
        if self.unit.is_leader():
            self.n2_provider.set_n2_information(
                amf_hostname=self.AMF_HOST,
                ngapp_port=self.NGAPP_PORT,
            )


if __name__ == "__main__":
    main(DummyFivegN2ProviderCharm)
```

"""


# TODO: get a valid id
LIBID = "4e70405e1ec34590ad4a3b0654d1f721"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft push-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# TODO: add your code here! Happy coding!
from typing import Dict
import logging
from typing import Optional

from interface_tester.schema_base import DataBagSchema  # type: ignore[import]
from ops.charm import CharmBase, CharmEvents, RelationChangedEvent
from pydantic import BaseModel, ValidationError
from ops.model import Relation
from ops.framework import EventBase, EventSource, Handle, Object

logger = logging.getLogger(__name__)
"""Schemas definition for the provider and requirer sides of the `fiveg_n2` interface.
It exposes two interfaces.schema_base.DataBagSchema subclasses called:
- ProviderSchema
- RequirerSchema
Examples:
    ProviderSchema:
        unit: <empty>
        app: {
            "amf_hostname": "amf",
<<<<<<< HEAD
            "ngapp_port": "38412"
=======
            "ngapp_port": 38412
>>>>>>> dev-implements-n2-interface
        }
    RequirerSchema:
        unit: <empty>
        app:  <empty>
"""
class ProviderAppData(BaseModel):
    """Provider app data for fiveg_n2."""
    amf_hostname: str
    ngapp_port: int

class ProviderSchema(DataBagSchema):
    """Provider schema for fiveg_n2."""
    app: ProviderAppData

def data_is_valid(data: dict) -> bool:
    """Returns whether data is valid.

    Args:
        data (dict): Data to be validated.

    Returns:
        bool: True if data is valid, False otherwise.
    """
    try:
        ProviderSchema(app=data)
        return True
    except ValidationError as e:
        logger.error("Invalid data: %s", e)
        return False

class N2InformationAvailableEvent(EventBase):
    """Charm event emitted when N2 information is available. It carries the AMF hostname."""

    def __init__(self, handle: Handle, amf_hostname: str, ngapp_port: int):
        """Init."""
        super().__init__(handle)
        self.amf_hostname = amf_hostname
        self.ngapp_port = ngapp_port

    def snapshot(self) -> dict:
        """Returns snapshot."""
        return {
            "amf_hostname": self.amf_hostname,
            "ngapp_port": self.ngapp_port
        }

    def restore(self, snapshot: dict) -> None:
        """Restores snapshot."""
        self.amf_hostname = snapshot["amf_hostname"]
        self.ngapp_port = snapshot["ngapp_port"]

class N2RequirerCharmEvents(CharmEvents):
    """List of events that the N2 requirer charm can leverage."""
    n2_information_available = EventSource(N2InformationAvailableEvent)

class N2Requires(Object):
    """Class to be instantiated by the N2 requirer charm."""

    on = N2RequirerCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handler triggered on relation changed event.

        Args:
            event (RelationChangedEvent): Juju event.

        Returns:
            None
        """
        if remote_app_relation_data := self._get_remote_app_relation_data(event.relation):
            self.on.n2_information_available.emit(
                amf_hostname=remote_app_relation_data["amf_hostname"],
                ngapp_port=remote_app_relation_data["ngapp_port"],
            )

    @property
    def amf_hostname(self) -> Optional[str]:
        """Returns AMF hostname.

        Returns:
            str: AMF hostname.
        """
        if remote_app_relation_data := self._get_remote_app_relation_data():
            return remote_app_relation_data.get("amf_hostname")
        return None

    @property
    def ngapp_port(self) -> Optional[int]:
        """Returns AMF's NGAPP port.

        Returns:
            int: AMF NGAPP port.
        """
        if remote_app_relation_data := self._get_remote_app_relation_data():
            return int(remote_app_relation_data.get("ngapp_port"))  # type: ignore[arg-type]
        return None

    def _get_remote_app_relation_data(
        self, relation: Optional[Relation] = None
    ) -> Optional[Dict[str, str]]:
        """Get relation data for the remote application.

        Args:
            Relation: Juju relation object (optional).

        Returns:
            Dict: Relation data for the remote application
            or None if the relation data is invalid.
        """
        relation = relation or self.model.get_relation(self.relation_name)
        if not relation:
            logger.error("No relation: %s", self.relation_name)
            return None
        if not relation.app:
            logger.warning("No remote application in relation: %s", self.relation_name)
            return None
        remote_app_relation_data = dict(relation.data[relation.app])
        if not data_is_valid(remote_app_relation_data):
            logger.error("Invalid relation data: %s", remote_app_relation_data)
            return None
        return remote_app_relation_data

class N2Provides(Object):
    """Class to be instantiated by the charm providing the N2 data."""

    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.relation_name = relation_name
        self.charm = charm

    def set_n2_information(self, amf_hostname: str, ngapp_port: int) -> None:
        """Sets the hostname and the ngapp port in the application relation data.

        Args:
            amf_hostname (str): AMF hostname.
            ngapp_port (int): AMF NGAPP port.
        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            raise RuntimeError("Unit must be leader to set application relation data.")
        relations = self.model.relations[self.relation_name]
        if not relations:
            raise RuntimeError(f"Relation {self.relation_name} not created yet.")
        if not data_is_valid(
                {
                    "amf_hostname": amf_hostname,
                    "ngapp_port": ngapp_port
                }
            ):
            raise ValueError(f"Invalid relation data")
        for relation in relations:
            relation.data[self.charm.app].update(
                {
                    "amf_hostname": amf_hostname,
                    "ngapp_port": str(ngapp_port)
                }
            )
