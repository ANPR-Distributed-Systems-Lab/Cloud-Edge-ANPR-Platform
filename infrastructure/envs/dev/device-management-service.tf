# device-management-service: everything the service owns, in one place.
# Image repository, DynamoDB tables, ECS service and the role its deploy workflow uses.
# Its API routes are registered in api.tf; the images bucket it signs URLs for is in storage.tf.

# ---------------------------------------------------------------- image repository

module "device_management_ecr" {
  source = "../../modules/ecr"

  name = "anpr/device-management-service"
}

# ---------------------------------------------------------------- database (DynamoDB)
# The key schemas must match the item classes of the service
# (internal/configuration/DeviceConfiguration, internal/status/DeviceStatus).

# One configuration item per device (diagram: PK id_urzadzenia, no sort key).
module "device_configurations_table" {
  source = "../../modules/dynamodb-table"

  name     = "${local.name}-device-configurations"
  hash_key = "deviceId"
}

# Heartbeat history of every device (diagram: PK id_urzadzenia, SK datetime).
# reportedAt is epoch milliseconds: a number, so a device's items sort chronologically.
# expiresAt (epoch seconds) lets DynamoDB delete old heartbeats for free once the service sets it.
module "device_statuses_table" {
  source = "../../modules/dynamodb-table"

  name           = "${local.name}-device-statuses"
  hash_key       = "deviceId"
  range_key      = "reportedAt"
  range_key_type = "N"
  ttl_attribute  = "expiresAt"
}

# ---------------------------------------------------------------- permissions of the application
# Used by the code in the container through the task role (no credentials to configure).

data "aws_iam_policy_document" "device_management_app" {
  # Item-level access to its two tables. No Scan: every access pattern goes by key.
  statement {
    sid = "ReadWriteDeviceTables"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:ConditionCheckItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      module.device_configurations_table.arn,
      module.device_statuses_table.arn,
    ]
  }

  # A presigned URL carries the permissions of whoever signed it: to let devices upload
  # images, the task role itself must be allowed to put objects under images/.
  statement {
    sid       = "SignImageUploads"
    actions   = ["s3:PutObject"]
    resources = ["${module.storage_bucket.arn}/${local.images_prefix}*"]
  }
}

# ---------------------------------------------------------------- service

module "device_management_service" {
  source = "../../modules/ecs-service"

  name         = "${local.name}-device-management-service"
  cluster_arn  = module.cluster.cluster_arn
  namespace_id = module.cluster.namespace_id
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.public_subnet_ids

  ingress_security_group_id = aws_security_group.vpc_link.id

  image_repository_url = module.device_management_ecr.repository_url

  # Names of the resources above; none of them is secret.
  environment = {
    DEVICE_CONFIGURATIONS_TABLE = module.device_configurations_table.name
    DEVICE_STATUSES_TABLE       = module.device_statuses_table.name
    IMAGES_BUCKET               = module.storage_bucket.name
  }

  task_role_policies = {
    device-management-app = data.aws_iam_policy_document.device_management_app.json
  }

  # Zero tasks until the first image exists in ECR; the pipeline deploys it, then the
  # "start environment" workflow (or a manual scale-up) switches it on.
  desired_count = 0

  # Tasks the "start environment" workflow runs for this service (0 = never started automatically).
  start_count = 1
}

# ---------------------------------------------------------------- deploy role
# What the deploy workflow of this service may do: push to its repository and update its
# service, nothing else.

module "device_management_deploy_role" {
  source = "../../modules/github-deploy-role"

  name                 = "${local.name}-device-management-deploy"
  oidc_provider_arn    = aws_iam_openid_connect_provider.github.arn
  github_repository    = var.github_repository
  github_owner_id      = var.github_owner_id
  github_repository_id = var.github_repository_id
  github_environment   = var.environment

  ecr_repository_arn = module.device_management_ecr.repository_arn
  ecs_service_arn    = module.device_management_service.service_arn
  pass_role_arns = [
    module.device_management_service.execution_role_arn,
    module.device_management_service.task_role_arn,
  ]
}
