# Remote state: the bucket this very stack created.
# (Backend blocks cannot use variables, so the name is written out. An AWS
# account id is an identifier, not a secret.)
terraform {
  backend "s3" {
    bucket       = "anpr-tfstate-695313591790"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true # lock = a .tflock object next to the state, no DynamoDB table
  }
}
