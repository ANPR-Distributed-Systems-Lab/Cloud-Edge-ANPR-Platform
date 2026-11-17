# Models of the edge devices (ml-models): the plate detector and the OCR, in their own bucket.
#
#   models/{detector|ocr}/{version}/{file}          model.onnx, plate_config.yaml, ...
#   models/{detector|ocr}/{version}/release.json    the files of the version with their SHA-256 and size
#
# ml-models publishes a version with `anpr-publish-model` and the credentials of the developer; a version is
# written once and never changed. Which version a device runs is part of its configuration in
# device-management-service, which reads release.json and signs download URLs for the device
# (GET /api/v1/device/models). Devices never reach the bucket with their own credentials.

locals {
  models_prefix = "models/"
}

module "models_bucket" {
  source = "../../modules/s3-bucket"

  name = "${local.name}-models-${data.aws_caller_identity.current.account_id}"

  # A version is immutable; an accidental overwrite or delete stays recoverable.
  versioning = true
}
