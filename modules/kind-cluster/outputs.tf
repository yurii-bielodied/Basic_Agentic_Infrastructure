output "client_key" {
  value = kind_cluster.kind.client_key
}

output "ca" {
  value = kind_cluster.kind.cluster_ca_certificate
}

output "crt" {
  value = kind_cluster.kind.client_certificate
}

output "endpoint" {
  value = kind_cluster.kind.endpoint
}
