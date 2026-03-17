terraform {
  required_providers {
    kubectl = {
      source = "gavinbunney/kubectl"
    }
  }
}

resource "helm_release" "flux_operator" {
  name             = "flux-operator"
  namespace        = var.namespace
  repository       = "oci://ghcr.io/controlplaneio-fluxcd/charts"
  chart            = "flux-operator"
  create_namespace = true
}

resource "helm_release" "flux_instance" {
  depends_on = [helm_release.flux_operator]

  name       = "flux-instance"
  namespace  = var.namespace
  repository = "oci://ghcr.io/controlplaneio-fluxcd/charts"
  chart      = "flux-instance"
  wait       = true

  set = [{
    name  = "instance.distribution.version"
    value = "2.8.x"
  }]
}

resource "kubectl_manifest" "flux_git_repository" {
  depends_on = [helm_release.flux_instance]

  yaml_body = <<-YAML
    apiVersion: source.toolkit.fluxcd.io/v1
    kind: GitRepository
    metadata:
      name: infra
      namespace: "${var.namespace}"
    spec:
      interval: 1m
      url: "${var.github_repo_url}"
      ref:
        branch: main
      # Для приватного репо:
      # secretRef:
      #   name: "${var.namespace}"
  YAML
}

resource "kubectl_manifest" "infra_crds" {
  depends_on = [kubectl_manifest.flux_git_repository]

  yaml_body = <<-YAML
    apiVersion: kustomize.toolkit.fluxcd.io/v1
    kind: Kustomization
    metadata:
      name: infra-crds
      namespace: "${var.namespace}"
    spec:
      interval: 2m
      sourceRef:
        kind: GitRepository
        name: infra
      path: ./infra/crds
      prune: true
      wait: true
      retryInterval: 30s
  YAML
}

resource "kubectl_manifest" "infra_manifests" {
  depends_on = [kubectl_manifest.infra_crds]

  yaml_body = <<-YAML
    apiVersion: kustomize.toolkit.fluxcd.io/v1
    kind: Kustomization
    metadata:
      name: infra-manifests
      namespace: "${var.namespace}"
    spec:
      interval: 2m
      dependsOn:
        - name: infra-crds
      sourceRef:
        kind: GitRepository
        name: infra
      path: ./infra/manifests
      prune: true
      wait: true
      retryInterval: 30s
  YAML
}
