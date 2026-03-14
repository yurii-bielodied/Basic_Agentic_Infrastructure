terraform {
  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "0.10"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1.1"
    }
  }
}
