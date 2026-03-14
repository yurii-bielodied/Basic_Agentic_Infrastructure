module "kind_cluster" {
  source = "./modules/kind-cluster"
}

resource "null_resource" "install_gatewayapi" {
  depends_on = [module.kind_cluster]

  provisioner "local-exec" {
    command = "kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/experimental-install.yaml"
  }
}

resource "helm_release" "agentgateway_crds" {
  depends_on = [null_resource.install_gatewayapi]

  namespace        = "agentgateway-system"
  name             = "agentgateway-crds"
  repository       = "oci://ghcr.io/kgateway-dev/charts"
  chart            = "agentgateway-crds"
  version          = "v2.2.1"
  create_namespace = true
}

resource "helm_release" "agentgateway" {
  depends_on = [helm_release.agentgateway_crds]

  namespace  = "agentgateway-system"
  name       = "agentgateway"
  repository = "oci://ghcr.io/kgateway-dev/charts"
  chart      = "agentgateway"
  version    = "v2.2.1"
}

resource "null_resource" "manage_ollama_model" {
  provisioner "local-exec" {
    command = "ollama pull qwen3:14b"
  }

  provisioner "local-exec" {
    when    = destroy
    command = "ollama stop qwen3:14b"
  }
}

resource "helm_release" "kagent_crds" {
  depends_on = [helm_release.agentgateway]

  namespace        = "kagent"
  name             = "kagent-crds"
  repository       = "oci://ghcr.io/kagent-dev/kagent/helm"
  chart            = "kagent-crds"
  create_namespace = true
}

resource "helm_release" "kagent" {
  depends_on = [helm_release.kagent_crds, null_resource.manage_ollama_model]

  namespace  = "kagent"
  name       = "kagent"
  repository = "oci://ghcr.io/kagent-dev/kagent/helm"
  chart      = "kagent"
  set = [
    {
      name  = "providers.default"
      value = "ollama"
    },
    {
      name  = "providers.ollama.provider"
      value = "Ollama"
    },
    {
      name  = "providers.ollama.model"
      value = "qwen3:14b"
    },
    {
      name  = "providers.ollama.config.host"
      value = "http://host.docker.internal:11434"
    },
  ]
}
