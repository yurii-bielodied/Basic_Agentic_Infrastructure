terraform {
  required_version = "~> 1.14"
  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "0.10"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1.1"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.19.0"
    }
  }
}
