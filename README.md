# Aether SD-Core AMF Operator (k8s)
[![CharmHub Badge](https://charmhub.io/sdcore-amf-k8s/badge.svg)](https://charmhub.io/sdcore-amf-k8s)

Charmed Operator for Aether SD-Core's Access and Mobility Management Function (AMF) for K8s.


## Pre-requisites

Juju model on a Kubernetes Cluster.

## Usage

```bash
juju deploy sdcore-amf-k8s --trust --channel=1.5/edge
juju deploy mongodb-k8s --trust --channel=6/beta
juju deploy sdcore-nrf-k8s --channel=1.5/edge
juju deploy self-signed-certificates --channel=stable
juju deploy sdcore-nms-k8s --channel=1.5/edge
juju integrate sdcore-nms-k8s:common_database mongodb-k8s:database
juju integrate sdcore-nms-k8s:auth_database mongodb-k8s:database
juju integrate sdcore-nms-k8s:certificates self-signed-certificates:certificates
juju integrate sdcore-nrf-k8s:database mongodb-k8s:database
juju integrate sdcore-nrf-k8s:certificates self-signed-certificates:certificates
juju integrate sdcore-nrf-k8s:sdcore_config sdcore-webui-k8s:sdcore-config
juju integrate sdcore-amf-k8s:fiveg_nrf sdcore-nrf-k8s:fiveg_nrf
juju integrate sdcore-amf-k8s:certificates self-signed-certificates:certificates
juju integrate sdcore-amf-k8s:sdcore_config sdcore-nms-k8s:sdcore_config
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

**amf**: ghcr.io/canonical/sdcore-amf:1.4.4
