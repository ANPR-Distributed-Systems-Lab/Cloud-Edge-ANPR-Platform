output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_family" {
  value = aws_ecs_task_definition.this.family
}

output "discovery_service_arn" {
  description = "Cloud Map service API Gateway integrates with."
  value       = aws_service_discovery_service.this.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

output "task_security_group_id" {
  value = aws_security_group.tasks.id
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "service_arn" {
  description = "ARN of the ECS service (aws_ecs_service.id is the ARN)."
  value       = aws_ecs_service.this.id
}
