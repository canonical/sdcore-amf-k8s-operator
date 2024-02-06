resource "juju_application" "amf" {
  name  = "amf"
  model = var.model_name

  charm {
    name    = "sdcore-amf-k8s"
    channel = var.channel
  }
  config = var.amf-config
  units  = 1
  trust  = true
}

resource "juju_integration" "amf-db" {
  model = var.model_name

  application {
    name     = juju_application.amf.name
    endpoint = "database"
  }

  application {
    name     = var.db_application_name
    endpoint = "database"
  }
}

resource "juju_integration" "amf-certs" {
  model = var.model_name

  application {
    name     = juju_application.amf.name
    endpoint = "certificates"
  }

  application {
    name     = var.certs_application_name
    endpoint = "certificates"
  }
}

resource "juju_integration" "amf-nrf" {
  model = var.model_name

  application {
    name     = juju_application.amf.name
    endpoint = "fiveg-nrf"
  }

  application {
    name     = var.nrf_application_name
    endpoint = "fiveg-nrf"
  }
}

