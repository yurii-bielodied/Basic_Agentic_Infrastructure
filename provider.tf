provider "kubernetes" {
  config_path = "${path.root}/kind-cluster-config"
}

provider "kind" {}

provider "helm" {
  kubernetes = {
    config_path = "${path.root}/kind-cluster-config"
  }
  repository_cache       = "${path.root}/.helmcache"
  repository_config_path = "${path.root}/.helmcache/repositories.yaml"
}

provider "kubectl" {
  host                   = module.kind_cluster.endpoint
  client_certificate     = module.kind_cluster.client_certificate
  client_key             = module.kind_cluster.client_key
  cluster_ca_certificate = module.kind_cluster.ca_certificate
  load_config_file       = false
}
