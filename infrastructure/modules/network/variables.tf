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
  description = "Number of Availability Zones to spread subnets over. At least 2: RDS subnet groups require it and it keeps services available if one zone fails."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2
    error_message = "az_count must be at least 2 (RDS subnet groups need two zones)."
  }
}

variable "subnet_newbits" {
  description = "Bits added to the VPC prefix for each subnet: /16 + 8 = /24 (256 addresses)."
  type        = number
  default     = 8
}
