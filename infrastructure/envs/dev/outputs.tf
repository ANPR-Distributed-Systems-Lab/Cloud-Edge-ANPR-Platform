output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "api_endpoint" {
  value = module.api.api_endpoint
}

output "operations_ecr_repository_url" {
  value = module.operations_ecr.repository_url
}

output "ecs_cluster_name" {
  value = module.cluster.cluster_name
}

output "operations_service_name" {
  value = module.operations_service.service_name
}
