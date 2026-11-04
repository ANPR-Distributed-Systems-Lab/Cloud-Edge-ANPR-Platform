# Bootstrap stack: the S3 bucket that stores Terraform state for every other stack.
#
# Chicken-and-egg: Terraform needs a state backend before it can manage anything.
# This stack is therefore applied once with local state and then migrated into
# the bucket it created (see backend.tf). It is rarely changed after that.

terraform {
  required_version = ">= 1.10" # S3 native state locking (use_lockfile) needs 1.10+

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Applied to every resource automatically; used for cost allocation and ownership.
  default_tags {
    tags = {
      Project   = "cloud-edge-anpr-platform"
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

# Reads the id of the account Terraform is currently authenticated against.
data "aws_caller_identity" "current" {}

locals {
  # Bucket names are unique across ALL AWS accounts. The account id makes the
  # name globally unique without random suffixes.
  state_bucket_name = "anpr-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  # State is the only record of what Terraform built. Losing it means losing
  # control of the infrastructure, so `terraform destroy` must fail here.
  lifecycle {
    prevent_destroy = true
  }
}

# Keeps every previous state file, so a bad apply can be rolled back.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# State may contain sensitive values (e.g. generated passwords): encrypt at rest.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Blocks every form of public access, regardless of policies attached later.
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Every apply creates a new state version; expire old ones to keep storage costs flat.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# Rejects any request that is not made over TLS.
data "aws_iam_policy_document" "tfstate" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate.json

  # The public access block and the policy both modify the bucket's policy
  # settings; applying them sequentially avoids a race condition.
  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

output "state_bucket_name" {
  value = aws_s3_bucket.tfstate.id
}
