terraform {
  required_providers {
    kind = {
      source = "tehcyx/kind"
    }
  }
}

resource "kind_cluster" "kind" {
  name           = "kind-cluster"
  wait_for_ready = true
}
