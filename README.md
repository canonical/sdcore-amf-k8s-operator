# SD-Core AMF Operator for K8s
[![CharmHub Badge](https://charmhub.io/sdcore-amf-k8s/badge.svg)](https://charmhub.io/sdcore-amf-k8s)

Charmed Operator for SD-Core's Access and Mobility Management Function (AMF) for K8s.


## Pre-requisites

Juju model on a Kubernetes cluster.

## Usage

```bash
juju deploy sdcore-amf-k8s --trust --channel=edge
juju deploy mongodb-k8s --trust --channel=5/edge
juju deploy sdcore-nrf-k8s --channel=edge
juju deploy self-signed-certificates --channel=beta
juju integrate sdcore-nrf-k8s:database mongodb-k8s
juju integrate sdcore-nrf-k8s:certificates self-signed-certificates:certificates
juju integrate sdcore-amf-k8s:database mongodb-k8s
juju integrate sdcore-amf-k8s:fiveg-nrf sdcore-nrf-k8s:fiveg-nrf
juju integrate sdcore-amf-k8s:certificates self-signed-certificates:certificates
```

### Overriding external access information for N2 interface

By default, the N2 connection information sent to the RAN will be taken from
the created `LoadBalancer` Kubernetes Service. If this is not appropriate with
your network configuration, you can override that information through
configuration:

```bash
juju config sdcore-amf-k8s external-amf-ip=192.168.0.4 external-amf-hostname=amf.example.com
```

## Image

**amf**: ghcr.io/canonical/sdcore-amf:1.3
