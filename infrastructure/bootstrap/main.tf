# Bootstrap: the S3 bucket that holds Terraform state for every other stack.
#
# Chicken-and-egg: Terraform needs a place to store state before it can manage
# anything, so this stack is applied once with LOCAL state, then migrated into
# the bucket it created (see backend.tf and the README).

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

  # Every resource gets these tags automatically (cost allocation, ownership).
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

data "aws_caller_identity" "current" {}

locals {
  # S3 bucket names are global across all AWS accounts, so the account id
  # makes the name unique without inventing random suffixes.
  state_bucket_name = "anpr-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  # State files are the only record of what Terraform built. Losing the bucket
  # means losing control of the infrastructure, so refuse to destroy it.
  lifecycle {
    prevent_destroy = true
  }
}

# Versioning keeps every previous state file, so a bad apply can be rolled back.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# State can contain sensitive values, so encrypt at rest.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block every form of public access, whatever policies get attached later.
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Old state versions pile up with every apply; drop them after 90 days.
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

# Refuse any request that is not made over TLS.
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

  # The public access block and the policy are both updated through the bucket's
  # policy API, so apply them one after another to avoid a race.
  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

output "state_bucket_name" {
  value = aws_s3_bucket.tfstate.id
}
