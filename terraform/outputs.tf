# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.amf.name
}

output "requires" {
  value = {
    fiveg_nrf = "fiveg_nrf"
    sdcore_config = "sdcore_config"
    certificates = "certificates"
    logging = "logging"
  }
}

output "provides" {
  value = {
    metrics = "metrics-endpoint"
    fiveg_n2 = "fiveg-n2"
  }
}
