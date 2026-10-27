# ---------------------------------------------------------------- platform

output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "ecs_cluster_name" {
  value = module.cluster.cluster_name
}

output "api_endpoint" {
  description = "Public base URL of the API."
  value       = module.api.api_endpoint
}

# ---------------------------------------------------------------- GitHub workflows
# Role ARNs to store as variables of the GitHub environment 'dev' (Settings -> Environments).

output "env_power_role_arn" {
  description = "Set as AWS_POWER_ROLE_ARN."
  value       = module.env_power_role.role_arn
}

# ---------------------------------------------------------------- operations-service

output "operations_ecr_repository_url" {
  value = module.operations_ecr.repository_url
}

output "operations_service_name" {
  value = module.operations_service.service_name
}

output "operations_deploy_role_arn" {
  description = "Set as AWS_OPERATIONS_DEPLOY_ROLE_ARN."
  value       = module.operations_deploy_role.role_arn
}

# ---------------------------------------------------------------- device-management-service

output "device_management_ecr_repository_url" {
  value = module.device_management_ecr.repository_url
}

output "device_management_service_name" {
  value = module.device_management_service.service_name
}

output "device_management_deploy_role_arn" {
  description = "Set as AWS_DEVICE_MANAGEMENT_DEPLOY_ROLE_ARN."
  value       = module.device_management_deploy_role.role_arn
}

# ---------------------------------------------------------------- events and storage

output "edge_events_topic_arn" {
  value = aws_sns_topic.edge_events.arn
}

output "operations_events_queue_url" {
  value = module.operations_events_queue.queue_url
}

output "operations_events_dlq_url" {
  description = "Messages operations-service failed to process 5 times; inspect and redrive from here."
  value       = module.operations_events_queue.dlq_url
}

output "storage_bucket_name" {
  value = module.storage_bucket.name
}

output "device_configurations_table_name" {
  value = module.device_configurations_table.name
}

output "device_statuses_table_name" {
  value = module.device_statuses_table.name
}
