<div align="center">
  <img src="./icon.svg" alt="ONF Icon" width="200" height="200">
</div>
<br/>
<div align="center">
  <a href="https://charmhub.io/sdcore-amf"><img src="https://charmhub.io/sdcore-amf/badge.svg" alt="CharmHub Badge"></a>
  <a href="https://github.com/canonical/sdcore-amf-operator/actions/workflows/publish-charm.yaml">
    <img src="https://github.com/canonical/sdcore-amf-operator/actions/workflows/publish-charm.yaml/badge.svg?branch=main" alt=".github/workflows/publish-charm.yaml">
  </a>
  <br/>
  <br/>
  <h1>SD-CORE AMF Operator</h1>
</div>

# sdcore-amf-operator

Charmed Operator for SDCORE's Access and Mobility Management Function (AMF).


## Pre-requisites

Juju model on a Kubernetes cluster.

## Usage

```bash
juju deploy sdcore-amf --trust --channel=edge
juju deploy mongodb-k8s --trust --channel=edge
juju deploy sdcore-nrf --trust --channel=edge
juju relate sdcore-amf:default-database mongodb-k8s
juju relate sdcore-amf:amf-database mongodb-k8s
juju relate sdcore-amf:fiveg-nrf sdcore-nrf:fiveg-nrf
```

## Image

**amf**: omecproject/5gc-amf:master-a4759db
