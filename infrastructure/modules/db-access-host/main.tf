# A small EC2 instance through which an administrator reaches the private databases (pgAdmin on
# a laptop) and through which the reset of the environment runs SQL.
#
# There is no SSH, no key pair and no inbound rule at all: AWS Systems Manager (SSM) Session
# Manager opens the session over the instance's outbound HTTPS connection, and IAM decides who
# may use it. The instance sits in a public subnet only to have that outbound route (the VPC has
# no NAT gateway). The environment start/stop workflows switch it on and off together with the
# databases (tag finops:switch).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

variable "name" {
  description = "Name prefix, e.g. anpr-dev-db-access."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  description = "Range of the VPC: the databases the host may reach are inside it."
  type        = string
}

variable "subnet_id" {
  description = "A public subnet: the host needs a public IP to reach SSM and the package repository."
  type        = string
}

variable "instance_type" {
  description = "Graviton. The host only forwards ports and runs psql, but installing packages needs more than the 0.5 GB of a t4g.nano (dnf is killed)."
  type        = string
  default     = "t4g.micro"
}

variable "database_port" {
  type    = number
  default = 5432
}

variable "readable_parameter_arns" {
  description = "SSM parameters the host may read, e.g. the password of a database that its scripts connect to."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------- image

# The current Amazon Linux 2023 image for arm64. It ships the SSM agent.
data "aws_ssm_parameter" "image" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# What the SSM agent needs to register the instance and accept sessions and commands.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Count (not for_each): the ARNs are only known after apply, but their number is not.
resource "aws_iam_role_policy" "parameters" {
  count = length(var.readable_parameter_arns) > 0 ? 1 : 0

  name = "read-parameters"
  role = aws_iam_role.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = var.readable_parameter_arns
    }]
  })
}

resource "aws_iam_instance_profile" "this" {
  name = var.name
  role = aws_iam_role.this.name
}

# ---------------------------------------------------------------- network

resource "aws_security_group" "this" {
  name        = var.name
  description = "Database access host ${var.name}: no inbound traffic"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-sg"
  }
}

# SSM, and the package repository (also HTTPS), live outside the VPC.
resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS to AWS Systems Manager and the package repository"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "database" {
  security_group_id = aws_security_group.this.id
  description       = "The databases inside the VPC"
  ip_protocol       = "tcp"
  from_port         = var.database_port
  to_port           = var.database_port
  cidr_ipv4         = var.vpc_cidr
}

# ---------------------------------------------------------------- instance

resource "aws_instance" "this" {
  ami                         = data.aws_ssm_parameter.image.value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
  associate_public_ip_address = true

  # Installed at the first boot: psql is what the reset and manual checks run. The host keeps no
  # state, so a changed script replaces it.
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y postgresql17
  EOT

  user_data_replace_on_change = true

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  tags = {
    Name = var.name

    # Read by the environment start/stop workflows (infrastructure/scripts/environment/environment_power.py).
    "finops:switch" = "true"
  }

  lifecycle {
    # A newer image is published every few weeks; the instance is not replaced because of it.
    ignore_changes = [ami]
  }
}

output "instance_id" {
  description = "Target of the SSM sessions."
  value       = aws_instance.this.id
}

output "security_group_id" {
  description = "Add it to the databases' allowed security groups."
  value       = aws_security_group.this.id
}
