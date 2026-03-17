terraform {
  required_providers {
    kubectl = {
      source = "gavinbunney/kubectl"
    }
  }
}

resource "helm_release" "agentgateway_crds" {
  namespace        = var.namespace
  name             = "agentgateway-crds"
  repository       = "oci://ghcr.io/kgateway-dev/charts"
  chart            = "agentgateway-crds"
  version          = "v2.2.2"
  create_namespace = true
}

resource "helm_release" "agentgateway" {
  depends_on = [helm_release.agentgateway_crds]

  namespace  = var.namespace
  name       = "agentgateway"
  repository = "oci://ghcr.io/kgateway-dev/charts"
  chart      = "agentgateway"
  version    = "v2.2.2"
  # set = [{
  #   name  = ""
  #   value = ""
  # }]
}

resource "kubectl_manifest" "agentgateway_parameters" {
  depends_on = [helm_release.agentgateway]

  yaml_body = yamlencode({
    apiVersion = "agentgateway.dev/v1alpha1"
    kind       = "AgentgatewayParameters"
    metadata = {
      name      = "agentgateway-config"
      namespace = "${var.namespace}"
    }
    spec = {
      logging = {
        format = "json"
      }
    }
  })
}

# resource "kubernetes_manifest" "agentgateway_proxy" {
#   depends_on = [helm_release.agentgateway]

#   manifest = {
#     apiVersion = "gateway.networking.k8s.io/v1"
#     kind       = "Gateway"
#     metadata = {
#       name      = "agentgateway-proxy"
#       namespace = "${var.namespace}"
#       labels = {
#         "gateway-type" = "ai-agents"
#       }
#     }
#     spec = {
#       gatewayClassName = "agentgateway"

#       infrastructure = {
#         parametersRef = {
#           name  = "agentgateway-config"
#           group = "agentgateway.dev"
#           kind  = "AgentgatewayParameters"
#         }
#       }

#       listeners = [
#         {
#           name     = "http"
#           protocol = "HTTP"
#           port     = 8080
#           allowedRoutes = {
#             namespaces = { from = "All" }
#             kinds      = [{ kind = "HTTPRoute" }]
#           }
#         },
#         # {
#         #   name     = "http-3000"
#         #   protocol = "HTTP"
#         #   port     = 3000
#         #   allowedRoutes = {
#         #     namespaces = { from = "All" }
#         #     kinds      = [{ kind = "HTTPRoute" }]
#         #   }
#         # }
#       ]
#     }
#   }
# }

resource "kubectl_manifest" "agentgateway_proxy" {
  depends_on = [helm_release.agentgateway, kubectl_manifest.agentgateway_parameters]

  yaml_body = yamlencode({
    apiVersion = "gateway.networking.k8s.io/v1"
    kind       = "Gateway"
    metadata = {
      name      = "agentgateway-proxy"
      namespace = "${var.namespace}"
      labels    = { "gateway-type" = "ai-agents" }
    }
    spec = {
      gatewayClassName = "agentgateway"

      infrastructure = {
        parametersRef = {
          name  = "agentgateway-config"
          group = "agentgateway.dev"
          kind  = "AgentgatewayParameters"
        }
      }

      listeners = [
        {
          name     = "http"
          protocol = "HTTP"
          port     = 8080
          allowedRoutes = {
            namespaces = { from = "All" }
            kinds      = [{ kind = "HTTPRoute" }]
          }
        },
        # {
        #   name     = "http-3000"
        #   protocol = "HTTP"
        #   port     = 3000
        #   allowedRoutes = {
        #     namespaces = { from = "All" }
        #     kinds      = [{ kind = "HTTPRoute" }]
        #   }
        # }
      ]
    }
  })
}

resource "kubectl_manifest" "kagent_ui_policy" {
  depends_on = [kubectl_manifest.agentgateway_proxy]

  yaml_body = yamlencode({
    apiVersion = "agentgateway.dev/v1alpha1"
    kind       = "AgentgatewayPolicy"
    metadata = {
      name      = "kagent-ui-basic-auth"
      namespace = "${var.namespace}"
    }
    spec = {
      targetRefs = [
        {
          group = "gateway.networking.k8s.io"
          kind  = "Gateway"
          name  = "agentgateway-proxy"
        }
      ]
      traffic = {
        basicAuthentication = {
          mode  = "Strict"
          realm = "Kagent UI"
          users = [
            # Example credentials (CHANGE IN PRODUCTION!):
            #   kagent-ui / KagentUI2026!
            "kagent-ui:$2y$05$h8tz.GowC3izTfjfP.BviegzYHbpZ8CS..2Gt9xxuRVWLBeHy8vxq"
          ]
        }
      }
    }
  })
}
