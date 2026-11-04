# ECS cluster and the Cloud Map namespace its services register in.
#
# Cloud Map is a service registry. When a task is healthy, ECS writes its private
# IP and port into the registry; API Gateway looks up live targets there for
# every request. This replaces a load balancer.

variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

# A cluster is a logical grouping; with Fargate there are no servers to manage.
resource "aws_ecs_cluster" "this" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "disabled" # extra CloudWatch metrics are billed; plain logs suffice for dev
  }
}

# ECS can register services only in DNS namespaces, not HTTP ones. A private DNS
# namespace also creates a Route 53 private hosted zone (0.50 USD/month).
resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = "${var.name}.local"
  description = "Service discovery for ${var.name}"
  vpc         = var.vpc_id
}

output "cluster_arn" {
  value = aws_ecs_cluster.this.arn
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "namespace_id" {
  value = aws_service_discovery_private_dns_namespace.this.id
}
