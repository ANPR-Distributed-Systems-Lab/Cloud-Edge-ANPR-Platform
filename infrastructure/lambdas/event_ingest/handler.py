"""Ingest endpoint of the edge devices: each request becomes one message on the platform's SNS topic.

API Gateway (HTTP API, payload format 2.0) invokes this function for the routes listed in
EVENT_TYPE_BY_ROUTE. The published message is:

    body        the request body, unchanged (a JSON object or array, at most MAX_BODY_BYTES)
    attributes  eventType   derived from the route, never taken from the client
                traceId     the client's X-Trace-Id header if valid, otherwise the API Gateway request id

Every queue subscribed to the topic receives a copy (fan-out). The response is 202 with the
message id, or an RFC 9457 problem (400, 404, 413, 503) carrying the same traceId.

Request bodies are never logged: they contain license plates and GPS positions (personal data).
"""

import base64
import binascii
import json
import logging
import os
import re
from http import HTTPStatus

import boto3
from botocore.exceptions import BotoCoreError, ClientError

TOPIC_ARN = os.environ["TOPIC_ARN"]
EVENT_TYPE_BY_ROUTE = json.loads(os.environ["EVENT_TYPE_BY_ROUTE"])  # set by Terraform from the route list

# SNS accepts 256 KiB per message including attributes; keep headroom for the attributes.
MAX_BODY_BYTES = 250 * 1024

# A client-supplied trace id is accepted only if it is short and plain, so it is safe to log and forward.
TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")

logger = logging.getLogger()  # level and JSON format come from the function's logging config
sns = boto3.client("sns")  # created once per execution environment and reused across invocations


def handler(event, context):
    trace_id = _trace_id(event)

    event_type = EVENT_TYPE_BY_ROUTE.get(event.get("routeKey"))
    if event_type is None:
        return _rejected(404, "UNKNOWN_ROUTE", "No event type is configured for this route.", trace_id)

    body = _raw_body(event)
    if body is None:
        return _rejected(400, "INVALID_BODY", "The body is not valid base64.", trace_id)
    if len(body) > MAX_BODY_BYTES:
        return _rejected(413, "PAYLOAD_TOO_LARGE", f"The body must not exceed {MAX_BODY_BYTES} bytes.", trace_id)

    message = _json_document(body)
    if message is None:
        return _rejected(400, "INVALID_JSON", "The body must be a UTF-8 JSON object or array.", trace_id)

    try:
        published = sns.publish(
            TopicArn=TOPIC_ARN,
            Message=message,
            MessageAttributes={
                "eventType": {"DataType": "String", "StringValue": event_type},
                "traceId": {"DataType": "String", "StringValue": trace_id},
            },
        )
    except (BotoCoreError, ClientError):
        logger.exception("Event could not be published", extra={"eventType": event_type, "traceId": trace_id})
        return _problem(503, "PUBLISH_FAILED", "The event could not be accepted; retry later.", trace_id)

    logger.info(
        "Event published",
        extra={"eventType": event_type, "traceId": trace_id, "messageId": published["MessageId"], "bodyBytes": len(body)},
    )
    return _response(202, {"messageId": published["MessageId"], "traceId": trace_id}, trace_id)


# ---------------------------------------------------------------- request parsing


def _trace_id(event):
    """The client's X-Trace-Id when it is a plain token, otherwise the API Gateway request id."""
    client_trace_id = (event.get("headers") or {}).get("x-trace-id", "")  # payload 2.0 lower-cases header names
    if TRACE_ID_PATTERN.fullmatch(client_trace_id):
        return client_trace_id
    return event["requestContext"]["requestId"]


def _raw_body(event):
    """The body as bytes; API Gateway base64-encodes bodies it does not treat as text. None if not decodable."""
    body = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return body.encode("utf-8")
    try:
        return base64.b64decode(body, validate=True)
    except binascii.Error:
        return None


def _json_document(body):
    """The body as text if it is a UTF-8 JSON object or array (a batch), otherwise None."""
    try:
        text = body.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return None
    return text if isinstance(document, (dict, list)) else None


# ---------------------------------------------------------------- responses


def _rejected(status, code, detail, trace_id):
    """A client error: logged at INFO, since the request was wrong, not the platform."""
    logger.info("Event rejected", extra={"status": status, "code": code, "traceId": trace_id})
    return _problem(status, code, detail, trace_id)


def _problem(status, code, detail, trace_id):
    """RFC 9457 problem details, with the same `code` and `requestId` fields as the Spring services."""
    problem = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
        "requestId": trace_id,
    }
    return _response(status, problem, trace_id, content_type="application/problem+json")


def _response(status, body, trace_id, content_type="application/json"):
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type, "X-Trace-Id": trace_id},
        "body": json.dumps(body),
    }
