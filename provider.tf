provider "kubernetes" {
  config_path = "${path.root}/kind-cluster-config"
}

provider "helm" {
  kubernetes = {
    config_path = "${path.root}/kind-cluster-config"
  }
  repository_cache       = "${path.root}/.helmcache"
  repository_config_path = "${path.root}/.helmcache/repositories.yaml"
}
