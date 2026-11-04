# Private Docker image repository for one microservice.

variable "name" {
  description = "Repository name, e.g. anpr/operations-service."
  type        = string
}

variable "keep_last_images" {
  description = "How many images to keep; older ones are deleted to limit storage cost."
  type        = number
  default     = 10
}

resource "aws_ecr_repository" "this" {
  name = var.name

  # IMMUTABLE: a tag (we use the git commit sha) can never be overwritten, so
  # a tag always refers to exactly the same image. This makes deployments traceable.
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true # basic CVE scan on every push, at no extra cost
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Without this the repository grows with every deployment and so does the bill.
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the last ${var.keep_last_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_last_images
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "repository_arn" {
  value = aws_ecr_repository.this.arn
}
