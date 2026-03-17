module "kind_cluster" {
  source = "./modules/kind-cluster"
}

# resource "null_resource" "install_gatewayapi" {
#   depends_on = [module.kind_cluster]

#   provisioner "local-exec" {
#     command = "kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/experimental-install.yaml"
#   }
# }

resource "null_resource" "manage_ollama_model" {
  provisioner "local-exec" {
    command = "powershell -Command \"if (-not (ollama list | Select-String 'qwen3:14b')) { ollama pull qwen3:14b }\""
  }

  provisioner "local-exec" {
    when    = destroy
    command = "ollama stop qwen3:14b"
  }
}

module "flux" {
  # depends_on = [null_resource.install_gatewayapi, null_resource.manage_ollama_model]
  depends_on = [null_resource.manage_ollama_model]

  source          = "./modules/flux"
  namespace       = "flux-system"
  github_repo_url = var.github_repo_url
}

# module "agentgateway" {
#   depends_on = [null_resource.install_gatewayapi]

#   source    = "./modules/agentgateway"
#   namespace = "agentgateway-system"
# }

# module "kagent" {
#   depends_on = [module.agentgateway, null_resource.manage_ollama_model]

#   source           = "./modules/kagent"
#   namespace        = "kagent"
#   default_provider = "ollama"
#   ollama_provider  = "Ollama"
#   ollama_model     = "qwen3:14b"
#   ollama_host      = "http://host.docker.internal:11434"
# }
