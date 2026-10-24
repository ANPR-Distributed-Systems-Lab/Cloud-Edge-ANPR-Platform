# Environment "dev": the root module. Configures Terraform and the AWS provider,
# then composes reusable modules into one working environment.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives in the bootstrap bucket. A separate key per environment keeps
  # dev and any future environment from touching each other's state.
  backend "s3" {
    bucket       = "anpr-tfstate-695313591790"
    key          = "envs/dev/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  # Tags applied to every resource: ownership and cost allocation per environment.
  default_tags {
    tags = {
      Project     = "cloud-edge-anpr-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

locals {
  name = "anpr-${var.environment}" # prefix of all resource names, e.g. anpr-dev-vpc
}

module "network" {
  source = "../../modules/network"

  name = local.name
}
