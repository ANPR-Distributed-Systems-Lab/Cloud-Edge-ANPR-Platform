# device-management-service: everything the service owns, in one place.
# Image repository, DynamoDB tables, ECS service and the role its deploy workflow uses.
# Its API routes are registered in api.tf; the images bucket it signs URLs for is in storage.tf, the models
# bucket in models.tf;
# the topic it publishes pairing events to is in device-events.tf. The contract is
# device-management-service/device-management-api.yaml, the design docs/device-management.md.

# ---------------------------------------------------------------- image repository

module "device_management_ecr" {
  source = "../../modules/ecr"

  name = "anpr/device-management-service"
}

# ---------------------------------------------------------------- database (DynamoDB)
# The key schemas must match the item classes of the service (internal/devices/Device,
# internal/configuration/DeviceConfiguration, internal/metrics/Measurement).

# Registry of devices: one item per device with its owner (accountId), Cognito username and the
# version of its ownership. The index finds the device of an account (people call the API with
# their own account id, not the device id).
module "devices_table" {
  source = "../../modules/dynamodb-table"

  name     = "${local.name}-devices"
  hash_key = "deviceId"

  global_secondary_indexes = [
    { name = "accountId-index", hash_key = "accountId" },
  ]
}

# One configuration item per device (diagram: PK id_urzadzenia, no sort key).
module "device_configurations_table" {
  source = "../../modules/dynamodb-table"

  name     = "${local.name}-device-configurations"
  hash_key = "deviceId"
}

# Metrics history of every device (diagram: device_statuses, PK id_urzadzenia, SK datetime).
# recordedAt is the moment of the measurement in epoch milliseconds: a number, so a device's items
# sort chronologically. expiresAt (epoch seconds, 7 days after the measurement) lets DynamoDB delete
# old measurements for free.
module "device_metrics_table" {
  source = "../../modules/dynamodb-table"

  name           = "${local.name}-device-metrics"
  hash_key       = "deviceId"
  range_key      = "recordedAt"
  range_key_type = "N"
  ttl_attribute  = "expiresAt"
}

# ---------------------------------------------------------------- permissions of the application
# Used by the code in the container through the task role (no credentials to configure).

data "aws_iam_policy_document" "device_management_app" {
  # Item-level access to its tables. No Scan: every access pattern goes by key. Creating and deleting
  # a device writes the registry and the configuration in one transaction (TransactWriteItems needs
  # the item permissions only).
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
      module.devices_table.arn,
      module.device_configurations_table.arn,
      module.device_metrics_table.arn,
    ]
  }

  # The device of an account is found through the index of the registry.
  statement {
    sid       = "QueryDevicesByAccount"
    actions   = ["dynamodb:Query"]
    resources = ["${module.devices_table.arn}/index/*"]
  }

  # A presigned URL carries the permissions of whoever signed it: to let devices upload
  # images, the task role itself must be allowed to put objects under images/.
  statement {
    sid       = "SignImageUploads"
    actions   = ["s3:PutObject"]
    resources = ["${module.storage_bucket.arn}/${local.images_prefix}*"]
  }

  # Model downloads (models.tf): the service reads release.json of a version and signs GET URLs for its
  # files, which carry these permissions.
  statement {
    sid       = "ReadModels"
    actions   = ["s3:GetObject"]
    resources = ["${module.models_bucket.arn}/${local.models_prefix}*"]
  }

  # Without ListBucket S3 answers 403 instead of 404 for a missing key, and an unpublished model version
  # could not be told from a permission problem.
  statement {
    sid       = "ListModels"
    actions   = ["s3:ListBucket"]
    resources = [module.models_bucket.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.models_prefix}*"]
    }
  }

  # Creating a device: the service checks that the owner is a person (finds the user by sub and reads
  # its groups), creates the Cognito user of the device and puts it in the group of devices. Deleting
  # a device (or undoing a failed creation) deletes that user. The application only ever deletes
  # users it created as devices; IAM cannot narrow AdminDeleteUser to a group.
  statement {
    sid = "ManageDeviceUsers"
    actions = [
      "cognito-idp:ListUsers",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:AdminCreateUser",
      "cognito-idp:AdminSetUserPassword",
      "cognito-idp:AdminAddUserToGroup",
      "cognito-idp:AdminDeleteUser",
    ]
    resources = [module.user_pool.user_pool_arn]
  }

  # Announces pairings to the other services (device-events.tf). The topic is encrypted, so
  # publishing also needs the topic's key (the same one as edge-events).
  statement {
    sid       = "PublishDeviceEvents"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.device_events.arn]
  }

  statement {
    sid       = "UseTopicKey"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = [data.aws_kms_key.sns.arn]
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
    DEVICES_TABLE               = module.devices_table.name
    DEVICE_CONFIGURATIONS_TABLE = module.device_configurations_table.name
    DEVICE_METRICS_TABLE        = module.device_metrics_table.name
    IMAGES_BUCKET               = module.storage_bucket.name
    MODELS_BUCKET               = module.models_bucket.name
    DEVICE_EVENTS_TOPIC_ARN     = aws_sns_topic.device_events.arn
    USER_POOL_ID                = module.user_pool.user_pool_id
    USERS_GROUP                 = one([for group, type in local.account_type_by_group : group if type == "user"])
    DEVICES_GROUP               = one([for group, type in local.account_type_by_group : group if type == "device"])
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
