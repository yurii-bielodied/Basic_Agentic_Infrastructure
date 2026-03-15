terraform {
  required_providers {
    kind = {
      source = "tehcyx/kind"
    }
  }
}

resource "kind_cluster" "kind" {
  name           = "kind-cluster"
  node_image     = "kindest/node:v1.35.1"
  wait_for_ready = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"
    node {
      role = "control-plane"
    }
    node {
      role = "worker"
    }
    node {
      role = "worker"
    }
  }
}

resource "null_resource" "label_workers" {
  depends_on = [kind_cluster.kind]

  provisioner "local-exec" {
    command     = "kubectl get nodes -o name | Select-String 'worker' | ForEach-Object { kubectl label $_ 'node-role.kubernetes.io/worker=true' --overwrite }"
    interpreter = ["pwsh", "-Command"]
  }
}
