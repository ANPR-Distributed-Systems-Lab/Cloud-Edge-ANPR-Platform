output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "Used by security groups to allow traffic from inside the VPC only."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}
