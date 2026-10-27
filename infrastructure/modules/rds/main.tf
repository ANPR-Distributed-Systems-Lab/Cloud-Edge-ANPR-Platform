# PostgreSQL database for one microservice, in private subnets.
#
# Only the listed security groups (the service's tasks) can reach it; there is no
# public address and no developer access path. The connection settings are written
# to SSM Parameter Store, and ECS injects them into the container at startup.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

variable "name" {
  description = "Identifier prefix, e.g. anpr-dev-operations."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets in at least two Availability Zones (a DB subnet group requires it)."
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect on the database port (the service's tasks)."
  type        = list(string)
}

variable "ssm_prefix" {
  description = "Parameter path prefix, e.g. /anpr/dev/operations-service. Holds the url, username and password."
  type        = string
}

variable "database_name" {
  type = string
}

variable "master_username" {
  type = string
}

variable "engine_version" {
  description = "Major version only; minor versions are upgraded automatically."
  type        = string
  default     = "17"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Initial storage in GB."
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Storage autoscaling ceiling in GB (storage only ever grows)."
  type        = number
  default     = 50
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  description = "Blocks terraform destroy and console deletion until switched off."
  type        = bool
  default     = true
}

locals {
  port = 5432
}

# ---------------------------------------------------------------- credentials

# Generated once and kept in Terraform state (encrypted bucket). Alphanumeric only:
# RDS rejects some special characters and the password is passed as a plain env value.
resource "random_password" "master" {
  length  = 40
  special = false
}

# ---------------------------------------------------------------- network

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name        = "${var.name}-db"
  description = "Database ${var.name}: PostgreSQL from the service only"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-db-sg"
  }
}

# Count (not for_each) because the group ids are only known after apply.
resource "aws_vpc_security_group_ingress_rule" "from_service" {
  count = length(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.this.id
  description                  = "PostgreSQL from an allowed security group"
  ip_protocol                  = "tcp"
  from_port                    = local.port
  to_port                      = local.port
  referenced_security_group_id = var.allowed_security_group_ids[count.index]
}

# ---------------------------------------------------------------- database

resource "aws_db_instance" "this" {
  identifier = var.name

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name  = var.database_name
  username = var.master_username
  password = random_password.master.result
  port     = local.port

  storage_type          = "gp3"
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false

  # Single AZ keeps the cost down; Multi-AZ would double the instance price.
  multi_az = false

  backup_retention_period   = var.backup_retention_days
  copy_tags_to_snapshot     = true
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"

  auto_minor_version_upgrade = true
}

# ---------------------------------------------------------------- SSM parameters
# The service never sees Terraform; it reads these through ECS (see the ecs-service
# module's `secrets`). Standard tier parameters are free.

resource "aws_ssm_parameter" "url" {
  name  = "${var.ssm_prefix}/datasource-url"
  type  = "String"
  value = "jdbc:postgresql://${aws_db_instance.this.address}:${local.port}/${var.database_name}?sslmode=require"
}

resource "aws_ssm_parameter" "username" {
  name  = "${var.ssm_prefix}/datasource-username"
  type  = "String"
  value = var.master_username
}

resource "aws_ssm_parameter" "password" {
  name  = "${var.ssm_prefix}/datasource-password"
  type  = "SecureString" # encrypted with the AWS-managed key alias/aws/ssm
  value = random_password.master.result
}

output "ssm_parameter_arns" {
  description = "Spring Boot environment variable name -> SSM parameter ARN, ready for the ecs-service `secrets` input."
  value = {
    SPRING_DATASOURCE_URL      = aws_ssm_parameter.url.arn
    SPRING_DATASOURCE_USERNAME = aws_ssm_parameter.username.arn
    SPRING_DATASOURCE_PASSWORD = aws_ssm_parameter.password.arn
  }
}

output "endpoint_address" {
  value = aws_db_instance.this.address
}

output "security_group_id" {
  value = aws_security_group.this.id
}
