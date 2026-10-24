variable "name" {
  description = "Service name, also the ECS task family, e.g. anpr-dev-operations-service."
  type        = string
}

variable "cluster_arn" {
  type = string
}

variable "namespace_id" {
  description = "Cloud Map namespace the service registers in."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Subnets the tasks run in."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "True while tasks live in public subnets without NAT (they need it to reach ECR and CloudWatch)."
  type        = bool
  default     = true
}

variable "ingress_security_group_id" {
  description = "The only security group allowed to reach the container port (the API Gateway VPC link)."
  type        = string
}

variable "image_repository_url" {
  description = "ECR repository URL without a tag."
  type        = string
}

variable "initial_image_tag" {
  description = "Tag in the first task definition. The pipeline replaces it on every deploy."
  type        = string
  default     = "bootstrap"
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "cpu" {
  description = "Fargate CPU units (1024 = 1 vCPU). 512 + 1024 MiB is a sane floor for Spring Boot."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate memory in MiB."
  type        = number
  default     = 1024
}

variable "cpu_architecture" {
  description = "X86_64 or ARM64. Must match the architecture the pipeline builds the image for."
  type        = string
  default     = "X86_64"
}

variable "desired_count" {
  description = "Initial number of tasks. Afterwards the pipeline and FinOps scripts own it."
  type        = number
  default     = 0
}

variable "health_check_path" {
  description = "Path the container health check calls on localhost. Liveness (not full health) so a database blip does not make ECS kill every task. The application must serve it (Spring Boot: management.endpoint.health.probes.enabled=true)."
  type        = string
  default     = "/actuator/health/liveness"
}

variable "environment" {
  description = "Plain (non-secret) environment variables for the container."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Environment variable name -> SSM Parameter Store ARN. ECS reads the parameter at task start and injects the value; the execution role gets read access to exactly these parameters."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  type    = number
  default = 14
}
