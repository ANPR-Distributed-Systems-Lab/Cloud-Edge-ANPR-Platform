# Network for one environment: a VPC with public subnets across several
# Availability Zones and a route to the internet.
#
# There is deliberately no NAT Gateway (about 32 USD/month). Workloads that need
# outbound internet get a public IP and are protected by security groups instead.
# Private subnets for the database are added together with RDS.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # The first `az_count` zones of the region, e.g. eu-central-1a and eu-central-1b.
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

resource "aws_vpc" "this" {
  cidr_block = var.vpc_cidr

  # Required for name resolution of AWS endpoints (ECR, SSM, RDS) and Cloud Map.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.name}-vpc"
  }
}

# The VPC's door to the internet.
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name}-igw"
  }
}

# One public subnet per AZ, carved out of the VPC range: 10.0.0.0/24, 10.0.1.0/24, ...
# Spreading over zones keeps the service available if one zone fails.
resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, var.subnet_newbits, count.index)

  map_public_ip_on_launch = true

  tags = {
    Name = "${var.name}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

# Isolated subnets for databases: same zones as the public ones, but with no route to
# the internet. They are not associated with the public route table, so they use the
# VPC's main route table, which only contains the local route.
resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, var.subnet_newbits, var.private_subnet_offset + count.index)

  tags = {
    Name = "${var.name}-private-${local.azs[count.index]}"
    Tier = "private"
  }
}

# A subnet is "public" solely because its route table sends internet-bound
# traffic (0.0.0.0/0) to the Internet Gateway.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${var.name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# AWS creates a default security group that lets its members talk to each other.
# Managing it with no rules removes that implicit trust, so nothing can rely on
# it by accident; every workload defines its own security group.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name}-default-sg-unused"
  }
}
