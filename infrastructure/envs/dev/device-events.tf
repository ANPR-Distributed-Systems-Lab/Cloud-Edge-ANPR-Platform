# Events about the link between a device and the account that owns it (docs/events/device-events.md).
#
#   device-management-service --publish (after the DynamoDB write)--> SNS topic --> SQS queue per
#                                                                                    consuming service
#
# Every message on the topic is:
#   body        eventId, occurredAt, version, deviceId and, for device.paired, accountId
#   attributes  eventType   device.paired | device.unpaired (subscriptions filter on it)
#               traceId     trace id of the pairing request
#
# Consumers subscribe with the event-queue module, next to the rest of their service
# (see operations-service.tf). The publisher is device-management-service only: these events decide
# which account owns which data, so the topic is separate from edge-events, where the devices'
# ingest function publishes.

# ---------------------------------------------------------------- topic

resource "aws_sns_topic" "device_events" {
  name              = "${local.name}-device-events"
  kms_master_key_id = "alias/aws/sns" # same key as edge-events (data.aws_kms_key.sns, events.tf)
}

data "aws_iam_policy_document" "device_events_topic" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.device_events.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Nobody but the task role of device-management-service may publish, whatever their IAM policies
  # say: a forged device.paired would hand the data of a device to any account.
  statement {
    sid       = "OnlyDeviceManagementMayPublish"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.device_events.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values   = [module.device_management_service.task_role_arn]
    }
  }
}

resource "aws_sns_topic_policy" "device_events" {
  arn    = aws_sns_topic.device_events.arn
  policy = data.aws_iam_policy_document.device_events_topic.json
}
