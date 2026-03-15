terraform {
  required_providers {
    kubectl = {
      source = "gavinbunney/kubectl"
    }
  }
}

resource "helm_release" "kagent_crds" {
  namespace        = var.namespace
  name             = "kagent-crds"
  repository       = "oci://ghcr.io/kagent-dev/kagent/helm"
  chart            = "kagent-crds"
  create_namespace = true
}

resource "helm_release" "kagent" {
  depends_on = [helm_release.kagent_crds]

  namespace  = var.namespace
  name       = "kagent"
  repository = "oci://ghcr.io/kagent-dev/kagent/helm"
  chart      = "kagent"
  set = [
    {
      name  = "providers.default"
      value = var.default_provider
    },
    {
      name  = "providers.ollama.provider"
      value = var.ollama_provider
    },
    {
      name  = "providers.ollama.model"
      value = var.ollama_model
    },
    {
      name  = "providers.ollama.config.host"
      value = var.ollama_host
    },
    {
      name  = "tools.grafana-mcp.enabled"
      value = false
    },
    {
      name  = "tools.querydoc.enabled"
      value = false
    },
    {
      name  = "agents.argo-rollouts-agent.enabled"
      value = false
    },
    {
      name  = "agents.cilium-debug-agent.enabled"
      value = false
    },
    {
      name  = "agents.cilium-manager-agent.enabled"
      value = false
    },
    {
      name  = "agents.cilium-policy-agent.enabled"
      value = false
    },
    {
      name  = "agents.helm-agent.enabled"
      value = false
    },
    {
      name  = "agents.istio-agent.enabled"
      value = false
    },
    {
      name  = "agents.kgateway-agent.enabled"
      value = false
    },
    {
      name  = "agents.observability-agent.enabled"
      value = false
    },
    {
      name  = "agents.promql-agent.enabled"
      value = false
    }
  ]
}

resource "kubectl_manifest" "allow_gateway_to_kagent" {
  yaml_body = yamlencode({
    apiVersion = "gateway.networking.k8s.io/v1beta1"
    kind       = "ReferenceGrant"
    metadata = {
      name      = "allow-gateway-to-kagent"
      namespace = "${var.namespace}"
    }
    spec = {
      from = [
        {
          group     = "gateway.networking.k8s.io"
          kind      = "HTTPRoute"
          namespace = "agentgateway-system"
        }
      ]
      to = [
        {
          group = ""
          kind  = "Service"
        }
      ]
    }
  })
}

# resource "kubernetes_manifest" "kagent_ui_route" {
#   depends_on = [helm_release.kagent]

#   manifest = {
#     apiVersion = "gateway.networking.k8s.io/v1"
#     kind       = "HTTPRoute"
#     metadata = {
#       name      = "kagent-ui"
#       namespace = "${var.namespace}"
#     }
#     spec = {
#       parentRefs = [
#         {
#           name        = "agentgateway-proxy"
#           namespace   = "agentgateway-system"
#           sectionName = "http"
#         }
#       ]
#       rules = [
#         {
#           matches = [{ path = { type = "PathPrefix", value = "/k8s-agent" } }]
#           filters = [
#             {
#               type = "URLRewrite"
#               urlRewrite = {
#                 path = {
#                   type               = "ReplacePrefixMatch"
#                   replacePrefixMatch = "/agents/kagent/k8s-agent/chat"
#                 }
#               }
#             }
#           ]
#           backendRefs = [{ name = "kagent-ui", port = 8080 }]
#         },
#         {
#           matches     = [{ path = { type = "PathPrefix", value = "/" } }]
#           backendRefs = [{ name = "kagent-ui", port = 8080 }]
#         }
#       ]
#     }
#   }
# }

resource "kubectl_manifest" "kagent_ui_route" {
  depends_on = [helm_release.kagent]

  yaml_body = yamlencode({
    apiVersion = "gateway.networking.k8s.io/v1"
    kind       = "HTTPRoute"
    metadata = {
      name      = "kagent-ui"
      namespace = "${var.namespace}"
    }
    spec = {
      parentRefs = [
        {
          name        = "agentgateway-proxy"
          namespace   = "agentgateway-system"
          sectionName = "http"
        }
      ]
      rules = [
        {
          matches = [{
            path = {
              type  = "PathPrefix"
              value = "/k8s-agent"
            }
          }]
          filters = [
            {
              type = "URLRewrite"
              urlRewrite = {
                path = {
                  type               = "ReplacePrefixMatch"
                  replacePrefixMatch = "/agents/kagent/k8s-agent/chat"
                }
              }
            }
          ]
          backendRefs = [{
            name = "kagent-ui"
            port = 8080
          }]
        },
        {
          matches = [{
            path = {
              type  = "PathPrefix"
              value = "/"
            }
          }]
          backendRefs = [{
            name = "kagent-ui"
            port = 8080
          }]
        }
      ]
    }
  })
}

# resource "kubernetes_manifest" "a2a_discovery_route" {
#   depends_on = [helm_release.kagent]

#   manifest = {
#     apiVersion = "gateway.networking.k8s.io/v1"
#     kind       = "HTTPRoute"
#     metadata = {
#       name      = "a2a-discovery-route"
#       namespace = "${var.namespace}"
#       labels    = { "app" = "a2a-gateway" }
#     }
#     spec = {
#       parentRefs = [
#         {
#           name        = "agentgateway-proxy"
#           namespace   = "agentgateway-system"
#           sectionName = "http-3000"
#         }
#       ]
#       rules = [
#         {
#           matches = [{ path = { type = "PathPrefix", value = "/k8s-agent" } }]
#           filters = [
#             {
#               type = "URLRewrite"
#               urlRewrite = {
#                 path = {
#                   type               = "ReplacePrefixMatch"
#                   replacePrefixMatch = "/api/a2a/kagent/k8s-agent"
#                 }
#               }
#             }
#           ]
#           backendRefs = [{ name = "kagent-controller", port = 8083 }]
#         },
#         {
#           matches     = [{ path = { type = "PathPrefix", value = "/api/a2a/kagent/" } }]
#           backendRefs = [{ name = "kagent-controller", port = 8083 }]
#         }
#       ]
#     }
#   }
# }

# resource "kubectl_manifest" "a2a_discovery_route" {
#   depends_on = [helm_release.kagent]

#   yaml_body = yamlencode({
#     apiVersion = "gateway.networking.k8s.io/v1"
#     kind       = "HTTPRoute"
#     metadata = {
#       name      = "a2a-discovery-route"
#       namespace = "${var.namespace}"
#       labels    = { "app" = "a2a-gateway" }
#     }
#     spec = {
#       parentRefs = [
#         {
#           name        = "agentgateway-proxy"
#           namespace   = "agentgateway-system"
#           sectionName = "http-3000"
#         }
#       ]
#       rules = [
#         {
#           matches = [{
#             path = {
#               type  = "PathPrefix"
#               value = "/k8s-agent"
#             }
#           }]
#           filters = [
#             {
#               type = "URLRewrite"
#               urlRewrite = {
#                 path = {
#                   type               = "ReplacePrefixMatch"
#                   replacePrefixMatch = "/api/a2a/kagent/k8s-agent"
#                 }
#               }
#             }
#           ]
#           backendRefs = [{
#             name = "kagent-controller"
#             port = 8083
#           }]
#         },
#         {
#           matches = [{
#             path = {
#               type  = "PathPrefix"
#               value = "/api/a2a/kagent/"
#             }
#           }]
#           backendRefs = [{
#             name = "kagent-controller"
#             port = 8083
#           }]
#         }
#       ]
#     }
#   })
# }
