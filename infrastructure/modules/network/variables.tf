variable "name" {
  description = "Prefix for resource names and Name tags, e.g. anpr-dev."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the whole VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "How many availability zones to spread public subnets over. An ALB needs at least 2."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2
    error_message = "az_count must be at least 2 (an Application Load Balancer requires two zones)."
  }
}

variable "subnet_newbits" {
  description = "Bits added to the VPC prefix for each subnet: /16 + 8 = /24 (256 addresses)."
  type        = number
  default     = 8
}
