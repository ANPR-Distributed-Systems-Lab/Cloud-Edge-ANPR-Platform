# Remote state: stored in the bucket this very stack created.
#
# Backend blocks cannot reference variables, so the bucket name is literal.
# An AWS account id is an identifier, not a secret.
terraform {
  backend "s3" {
    bucket       = "anpr-tfstate-695313591790"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true # state lock = a .tflock object beside the state; no DynamoDB table needed
  }
}
