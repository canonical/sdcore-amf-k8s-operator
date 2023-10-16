# Contributing
To make contributions to this charm, you'll need a working Juju development setup.

## Prerequisites
### Charmcraft installation
Charmcraft depends on LXD to build the charms in a container matching the target base(s).

To install Charmcraft and LXD run the following commands:
```shell
sudo snap install --classic charmcraft
sudo snap install lxd
sudo adduser $USER lxd
newgrp lxd
lxd init --auto
```

### MicroK8s installation
To install MicroK8s run the following commands:
```shell
sudo snap install microk8s --channel=1.27-strict/stable
sudo usermod -a -G snap_microk8s $USER
newgrp snap_microk8s
sudo microk8s enable hostpath-storage
```

### Install Juju
To install Juju run the following command:
```shell
sudo snap install juju
```
To bootstrap a Juju controller on the MicroK8s instance run the following command:
```shell
juju bootstrap microk8s
```

### Install tox
This project requires `tox>=4.0.0` for development and testing, which is available as a `pip` package.

To install `pip` and `tox`, run the following commands:
```shell
sudo apt install python3-pip
python3 -m pip install tox
```

## Development
You can use the environments created by `tox` for development:
```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

## Testing
This project uses `tox` for managing test environments.

There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox -e lint          # code style
tox -e static        # static analysis
tox -e unit          # unit tests
tox -e integration   # integration tests
```

## Build
Go to the charm directory and run:
```bash
charmcraft pack
```
