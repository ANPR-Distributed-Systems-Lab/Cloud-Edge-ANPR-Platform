# Object storage shared by the services, split by key prefix (architecture diagram):
#
#   images/    vehicle and plate photos, uploaded by the devices with presigned URLs that
#              device-management-service generates
#   reports/   generated PDF reports (to come)
#
# Each service gets access to its prefixes only, in its own file.

data "aws_caller_identity" "current" {}

locals {
  images_prefix = "images/"
}

module "storage_bucket" {
  source = "../../modules/s3-bucket"

  # Bucket names are global across AWS; the account id keeps this one unique.
  name = "${local.name}-storage-${data.aws_caller_identity.current.account_id}"
}
