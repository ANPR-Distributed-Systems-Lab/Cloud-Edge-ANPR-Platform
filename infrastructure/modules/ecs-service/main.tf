# One microservice on ECS Fargate, registered in Cloud Map so API Gateway can reach it.
#
#   task (container) --registers--> Cloud Map <--looks up-- API Gateway --> internet

data "aws_region" "current" {}

# ---------------------------------------------------------------- logs

# Container stdout/stderr land here; retention keeps the CloudWatch bill bounded.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------- IAM
# Two roles with different jobs (a common source of confusion):
#   execution role = used by ECS itself to start the task (pull image, write logs)
#   task role      = used by the application code inside the container (SQS, SSM, S3...)

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# AWS-managed policy: pull from ECR and write to CloudWatch Logs.
resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Lets ECS read the listed SSM parameters when it starts a task, so secrets never
# appear in the task definition, the repository or the pipeline.
data "aws_iam_policy_document" "read_secrets" {
  count = length(var.secrets) > 0 ? 1 : 0

  statement {
    actions   = ["ssm:GetParameters"]
    resources = values(var.secrets)
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count = length(var.secrets) > 0 ? 1 : 0

  name   = "read-ssm-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets[0].json
}

# Intentionally empty (least privilege). Permissions are added here once the
# application needs SQS, SNS or SSM access.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# ---------------------------------------------------------------- network

resource "aws_security_group" "tasks" {
  name        = "${var.name}-tasks"
  description = "Tasks of ${var.name}: container port from the API Gateway VPC link only"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-tasks-sg"
  }
}

# Only API Gateway (via its VPC link) may reach the container. The task has a
# public IP for outbound traffic, but nothing from the internet can connect to it.
resource "aws_vpc_security_group_ingress_rule" "from_vpc_link" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "Container port from the API Gateway VPC link"
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  referenced_security_group_id = var.ingress_security_group_id
}

# Outbound is open: the task must reach ECR, CloudWatch and later SQS, SNS, SSM and RDS.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.tasks.id
  description       = "Outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ---------------------------------------------------------------- service discovery

# This service's entry in the registry. API Gateway needs the port as well as
# the IP, which only SRV records carry; A records cause "no target endpoints found".
resource "aws_service_discovery_service" "this" {
  name = var.name

  dns_config {
    namespace_id   = var.namespace_id
    routing_policy = "MULTIVALUE" # return every healthy task, not just one

    dns_records {
      type = "SRV"
      ttl  = 10 # short TTL: a replaced task disappears from lookups quickly
    }
  }

  # ECS reports task health to Cloud Map through this setting, so a task is listed only
  # once its container health check passes. failure_threshold is deprecated (AWS always
  # uses 1) but it must stay: with an empty block the provider sends nothing, AWS stores
  # no custom health check, and tasks would be listed the moment they start running.
  health_check_custom_config {
    failure_threshold = 1
  }
}

# ---------------------------------------------------------------- task + service

# Blueprint of the container. Terraform creates revision 1 with a placeholder
# image tag; the pipeline registers a new revision on every deployment.
resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc" # each task gets its own network interface and IP
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([{
    name      = var.name
    image     = "${var.image_repository_url}:${var.initial_image_tag}"
    essential = true # if this container stops, the whole task stops

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    environment = [for k, v in var.environment : { name = k, value = v }]

    # Resolved by ECS from SSM when the task starts (needs the execution role policy above).
    secrets = [for k, v in var.secrets : { name = k, valueFrom = v }]

    # Without a load balancer this is the only health check. A task is added to
    # Cloud Map once it passes and removed (and replaced) when it fails.
    # It runs inside the container, so the image must provide wget. 127.0.0.1 instead of
    # "localhost": busybox wget may resolve localhost to the IPv6 address first.
    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://127.0.0.1:${var.container_port}${var.health_check_path} || exit 1"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 90 # JVM startup time; failures during this window are ignored
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = data.aws_region.current.region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# Keeps the desired number of tasks running and replaces failed ones.
resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.this.arn
    container_name = var.name
    container_port = var.container_port
  }

  # If new tasks keep failing, roll back automatically to the last working version.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The pipeline owns the task definition (image version) and the FinOps scripts
  # own the task count. Terraform must not revert either on the next apply.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
