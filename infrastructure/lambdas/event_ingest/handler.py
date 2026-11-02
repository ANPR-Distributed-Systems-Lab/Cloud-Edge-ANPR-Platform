"""Ingest endpoint of the edge devices: each request becomes one message on the platform's SNS topic.

API Gateway (HTTP API, payload format 2.0) invokes this function for the routes listed in
EVENT_TYPE_BY_ROUTE, after its JWT authorizer has validated the device's access token. The
contracts are docs/api/ingest-detections.md and docs/api/ingest-device-locations.md.

The whole batch is validated first and atomically: any invalid item rejects the request with 400
VALIDATION_FAILED listing every problem found, and nothing is published. A valid batch is published as:

    body        the request body, unchanged (a JSON object, at most MAX_BODY_BYTES; unknown properties stay)
    attributes  eventType   derived from the route, never taken from the client
                traceId     the client's X-Trace-Id header if valid, otherwise the API Gateway request id
                deviceId    the id of the device (the token's sub), from the token (never from the body)

The owner of the device is not in the message: every consumer resolves it from its own copy of the
device pairing (see docs/identity-and-access.md).

Every queue subscribed to the topic receives a copy (fan-out). The response is 202 with the batch id
and the number of accepted items, or an RFC 9457 problem (400, 403, 404, 413, 415, 503) carrying the
same traceId.

Request bodies are never logged, and validation messages never repeat values: they contain license
plates and GPS positions (personal data).
"""

import base64
import binascii
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from http import HTTPStatus

import boto3
from botocore.exceptions import BotoCoreError, ClientError

TOPIC_ARN = os.environ["TOPIC_ARN"]
EVENT_TYPE_BY_ROUTE = json.loads(os.environ["EVENT_TYPE_BY_ROUTE"])  # set by Terraform from the route list

# Value of the account_type claim (see lambdas/token_claims) that identifies a device.
DEVICE_ACCOUNT_TYPE = "device"

# SNS accepts 256 KiB per message including attributes; keep headroom for the attributes.
MAX_BODY_BYTES = 250 * 1024

# A client-supplied trace id is accepted only if it is short and plain, so it is safe to log and forward.
TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")

# ---------------------------------------------------------------- rules of the contracts

MAX_DETECTIONS = 100
MAX_LOCATIONS = 500
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# RFC 3339 in UTC with "Z", at most millisecond precision.
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z")
PLATE_PATTERN = re.compile(r"[A-Z0-9]{3,8}")
# images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg, assigned by device-management with the presigned upload URL.
IMAGE_KEY_PATTERN = re.compile(
    r"images/(?P<device>[0-9a-fA-F-]{36})/\d{4}/\d{2}/\d{2}/(?P<frame>[0-9a-fA-F-]{36})\.jpg"
)
MAX_FUTURE = timedelta(minutes=5)  # tolerated clock skew of the device
MAX_AGE = timedelta(days=30)  # store-and-forward can deliver old data after a long outage

logger = logging.getLogger()  # level and JSON format come from the function's logging config
sns = boto3.client("sns")  # created once per execution environment and reused across invocations


def handler(event, context):
    trace_id = _trace_id(event)

    event_type = EVENT_TYPE_BY_ROUTE.get(event.get("routeKey"))
    if event_type is None:
        return _rejected(404, "UNKNOWN_ROUTE", "No event type is configured for this route.", trace_id)

    device_id = _device_id(event)
    if device_id is None:
        return _rejected(403, "FORBIDDEN", "The token is not a device token.", trace_id)

    if not _is_json_content_type(event):
        return _rejected(415, "UNSUPPORTED_MEDIA_TYPE", "The Content-Type must be application/json.", trace_id)

    body = _raw_body(event)
    if body is None:
        return _rejected(400, "INVALID_BODY", "The body is not valid base64.", trace_id)
    if len(body) > MAX_BODY_BYTES:
        return _rejected(413, "PAYLOAD_TOO_LARGE", f"The body must not exceed {MAX_BODY_BYTES} bytes.", trace_id)

    parsed = _json_object(body)
    if parsed is None:
        return _rejected(400, "INVALID_JSON", "The body must be a UTF-8 JSON object.", trace_id)
    message, document = parsed

    errors, accepted = VALIDATOR_BY_EVENT_TYPE[event_type](document, _now(), device_id)
    if errors:
        count = f"{len(errors)} validation error{'' if len(errors) == 1 else 's'}"
        return _rejected(400, "VALIDATION_FAILED", f"{count}, nothing was accepted", trace_id, fields=errors)

    try:
        published = sns.publish(
            TopicArn=TOPIC_ARN,
            Message=message,
            MessageAttributes={
                "eventType": {"DataType": "String", "StringValue": event_type},
                "traceId": {"DataType": "String", "StringValue": trace_id},
                "deviceId": {"DataType": "String", "StringValue": device_id},
            },
        )
    except (BotoCoreError, ClientError):
        logger.exception("Event could not be published", extra={"eventType": event_type, "traceId": trace_id})
        return _problem(503, "PUBLISH_FAILED", "The event could not be accepted; retry later.", trace_id)

    logger.info(
        "Event published",
        extra={
            "eventType": event_type,
            "traceId": trace_id,
            "deviceId": device_id,
            "batchId": document["batchId"],
            "accepted": accepted,
            "messageId": published["MessageId"],
            "bodyBytes": len(body),
        },
    )
    return _response(202, {"batchId": document["batchId"], "accepted": accepted, "traceId": trace_id}, trace_id)


def _now():
    """The current time; a function so that unit tests can fix it."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- request parsing


def _trace_id(event):
    """The client's X-Trace-Id when it is a plain token, otherwise the API Gateway request id."""
    client_trace_id = (event.get("headers") or {}).get("x-trace-id", "")  # payload 2.0 lower-cases header names
    if TRACE_ID_PATTERN.fullmatch(client_trace_id):
        return client_trace_id
    return event["requestContext"]["requestId"]


def _device_id(event):
    """The id of the device from the validated token, or None if the token is not a device token.

    sub is the id of the Cognito user, which for a device account is the device. account_type is added
    to the token by the user pool's pre token generation trigger. Without an authorizer on the route
    there are no claims at all, so the request is refused rather than published anonymously.
    """
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    device_id = claims.get("sub")
    return device_id if device_id and claims.get("account_type") == DEVICE_ACCOUNT_TYPE else None


def _is_json_content_type(event):
    """application/json, with or without parameters such as charset."""
    content_type = (event.get("headers") or {}).get("content-type", "")
    return content_type.split(";")[0].strip().lower() == "application/json"


def _raw_body(event):
    """The body as bytes; API Gateway base64-encodes bodies it does not treat as text. None if not decodable."""
    body = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return body.encode("utf-8")
    try:
        return base64.b64decode(body, validate=True)
    except binascii.Error:
        return None


def _json_object(body):
    """(text, parsed object) if the body is a UTF-8 JSON object, otherwise None. NaN and Infinity are not JSON."""

    def reject_constant(name):
        raise ValueError(f"{name} is not valid JSON")

    try:
        text = body.decode("utf-8")
        document = json.loads(text, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError):
        return None
    return (text, document) if isinstance(document, dict) else None


# ---------------------------------------------------------------- validation
#
# A validator returns (errors, number of items). Every error is {index, field, code, message}; index is the
# position of the item in the batch and is left out for errors about the batch itself. Messages describe
# the rule, never the value.


def _validate_detections(document, now, device_id):
    errors = []
    _check_uuid(errors, document, "batchId", "batchId", None)
    items = _check_array(errors, document, "detections", MAX_DETECTIONS)
    seen = set()
    for index, item in enumerate(items):
        path = f"detections[{index}]"
        if not isinstance(item, dict):
            _add(errors, path, "TYPE", "must be an object", index)
            continue
        detection_id = _check_uuid(errors, item, "detectionId", f"{path}.detectionId", index)
        if detection_id is not None:
            if detection_id.lower() in seen:
                _add(errors, f"{path}.detectionId", "DUPLICATE_DETECTION_ID", "appears twice in the batch", index)
            seen.add(detection_id.lower())
        frame_id = _check_uuid(errors, item, "frameId", f"{path}.frameId", index)
        _check_timestamp(errors, item, "detectedAt", f"{path}.detectedAt", index, now)
        _check_plate(errors, item, f"{path}.plate", index)
        _check_number(errors, item, "ocrConfidence", f"{path}.ocrConfidence", index, 0, 1)
        _check_number(errors, item, "detectorConfidence", f"{path}.detectorConfidence", index, 0, 1)
        _check_image_key(errors, item, f"{path}.imageKey", index, device_id, frame_id)
        _check_corners(errors, item, f"{path}.corners", index)
        _check_detection_location(errors, item, f"{path}.location", index)
    return errors, len(items)


def _validate_locations(document, now, device_id):
    errors = []
    _check_uuid(errors, document, "batchId", "batchId", None)
    items = _check_array(errors, document, "locations", MAX_LOCATIONS)
    seen = set()
    for index, item in enumerate(items):
        path = f"locations[{index}]"
        if not isinstance(item, dict):
            _add(errors, path, "TYPE", "must be an object", index)
            continue
        location_id = _check_uuid(errors, item, "locationId", f"{path}.locationId", index)
        if location_id is not None:
            if location_id.lower() in seen:
                _add(errors, f"{path}.locationId", "DUPLICATE_LOCATION_ID", "appears twice in the batch", index)
            seen.add(location_id.lower())
        _check_timestamp(errors, item, "recordedAt", f"{path}.recordedAt", index, now)
        _check_coordinates(errors, item, path, index)
        _check_number(errors, item, "accuracyM", f"{path}.accuracyM", index, 0, None, required=False)
        _check_number(errors, item, "speedMps", f"{path}.speedMps", index, 0, None, required=False)
        _check_number(errors, item, "headingDeg", f"{path}.headingDeg", index, 0, 360, required=False,
                      maximum_exclusive=True)
    return errors, len(items)


# Every event type of EVENT_TYPE_BY_ROUTE needs a validator; a route without one fails at start-up, not per request.
VALIDATOR_BY_EVENT_TYPE = {"detection": _validate_detections, "device-location": _validate_locations}
_without_validator = set(EVENT_TYPE_BY_ROUTE.values()) - set(VALIDATOR_BY_EVENT_TYPE)
if _without_validator:
    raise RuntimeError(f"No body validator for event types {sorted(_without_validator)}")


def _add(errors, field, code, message, index):
    error = {"field": field, "code": code, "message": message}
    if index is not None:
        error = {"index": index, **error}
    errors.append(error)


def _present(errors, obj, name, path, index, required=True):
    """True if obj has a non-null value for name; a missing required value is recorded as REQUIRED."""
    if obj.get(name) is not None:
        return True
    if required:
        _add(errors, path, "REQUIRED", "is required", index)
    return False


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_array(errors, document, name, maximum):
    """The items of the batch array, or an empty list if it is missing or not an array."""
    if not _present(errors, document, name, name, None):
        return []
    items = document[name]
    if not isinstance(items, list):
        _add(errors, name, "TYPE", "must be an array", None)
        return []
    if not 1 <= len(items) <= maximum:
        _add(errors, name, "SIZE", f"must contain 1 to {maximum} items", None)
        return []
    return items


def _check_uuid(errors, obj, name, path, index):
    """The value if it is a UUID, otherwise None (and the error is recorded)."""
    if not _present(errors, obj, name, path, index):
        return None
    value = obj[name]
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        _add(errors, path, "FORMAT", "must be a UUID", index)
        return None
    return value


def _check_timestamp(errors, obj, name, path, index, now):
    if not _present(errors, obj, name, path, index):
        return
    value = obj[name]
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        _add(errors, path, "FORMAT", "must be an RFC 3339 UTC timestamp ending with Z", index)
        return
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # e.g. month 13
        _add(errors, path, "FORMAT", "must be an RFC 3339 UTC timestamp ending with Z", index)
        return
    if moment > now + MAX_FUTURE:
        _add(errors, path, "TIMESTAMP_IN_FUTURE", "is more than 5 minutes in the future", index)
    elif moment < now - MAX_AGE:
        _add(errors, path, "TIMESTAMP_TOO_OLD", "is more than 30 days old", index)


def _check_plate(errors, item, path, index):
    if not _present(errors, item, "plate", path, index):
        return
    value = item["plate"]
    if not isinstance(value, str):
        _add(errors, path, "TYPE", "must be a string", index)
    elif not PLATE_PATTERN.fullmatch(value):
        _add(errors, path, "PATTERN", "must match ^[A-Z0-9]{3,8}$", index)


def _check_number(errors, obj, name, path, index, minimum, maximum, required=True, maximum_exclusive=False,
                  integer=False):
    if not _present(errors, obj, name, path, index, required):
        return
    value = obj[name]
    if not _is_number(value) or (integer and not isinstance(value, int)):
        _add(errors, path, "TYPE", "must be an integer" if integer else "must be a number", index)
        return
    too_high = maximum is not None and (value >= maximum if maximum_exclusive else value > maximum)
    if value < minimum or too_high:
        if maximum is None:
            message = f"must be {minimum} or more"
        else:
            message = f"must be between {minimum} and {maximum}" + (" (exclusive)" if maximum_exclusive else "")
        _add(errors, path, "RANGE", message, index)


def _check_image_key(errors, item, path, index, device_id, frame_id):
    """The key of the photo of this frame, under the prefix of the calling device."""
    if not _present(errors, item, "imageKey", path, index):
        return
    value = item["imageKey"]
    if not isinstance(value, str):
        _add(errors, path, "TYPE", "must be a string", index)
        return
    match = IMAGE_KEY_PATTERN.fullmatch(value)
    if match is None:
        _add(errors, path, "FORMAT", "must be images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg", index)
    elif match["device"].lower() != device_id.lower():
        _add(errors, path, "IMAGE_KEY_FOREIGN", "must be under the prefix of the calling device", index)
    elif frame_id is not None and match["frame"].lower() != frame_id.lower():
        _add(errors, path, "FORMAT", "file name must be the frameId of the detection", index)


def _check_corners(errors, item, path, index):
    """4 points [x, y] normalized to 0-1, top-left, top-right, bottom-right, bottom-left.

    Image coordinates grow downwards, so going clockwise on screen every turn has a positive cross product;
    all four positive means clockwise, convex and not degenerate (a self-intersecting quadrilateral mixes signs).
    """
    if not _present(errors, item, "corners", path, index):
        return
    points = item["corners"]
    shape_ok = (
        isinstance(points, list)
        and len(points) == 4
        and all(isinstance(p, list) and len(p) == 2 and all(_is_number(c) for c in p) for p in points)
    )
    if not shape_ok:
        _add(errors, path, "INVALID_CORNERS", "must be 4 points [x, y] of numbers", index)
        return
    if any(not 0 <= c <= 1 for p in points for c in p):
        _add(errors, path, "RANGE", "coordinates must be between 0 and 1", index)
        return
    for i in range(4):
        (ax, ay), (bx, by), (cx, cy) = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 1e-12:
            _add(errors, path, "INVALID_CORNERS",
                 "must be top-left, top-right, bottom-right, bottom-left: clockwise, convex, not degenerate", index)
            return


def _check_coordinates(errors, obj, path, index):
    """lat and lon of obj (WGS84), and not the 0, 0 that GPS modules report without a fix."""
    _check_number(errors, obj, "lat", f"{path}.lat", index, -90, 90)
    _check_number(errors, obj, "lon", f"{path}.lon", index, -180, 180)
    lat, lon = obj.get("lat"), obj.get("lon")
    if _is_number(lat) and _is_number(lon) and lat == 0 and lon == 0:
        _add(errors, path, "INVALID_LOCATION", "0, 0 is not a valid position (no GPS fix)", index)


def _check_detection_location(errors, item, path, index):
    if not _present(errors, item, "location", path, index):
        return
    location = item["location"]
    if not isinstance(location, dict):
        _add(errors, path, "TYPE", "must be an object", index)
        return
    _check_coordinates(errors, location, path, index)
    _check_number(errors, location, "accuracyM", f"{path}.accuracyM", index, 0, None, required=False)
    _check_number(errors, location, "fixAgeMs", f"{path}.fixAgeMs", index, 0, None, required=False, integer=True)


# ---------------------------------------------------------------- responses


def _rejected(status, code, detail, trace_id, fields=None):
    """A client error: logged at INFO (without values), since the request was wrong, not the platform."""
    extra = {"status": status, "code": code, "traceId": trace_id}
    if fields:
        extra["errorCount"] = len(fields)
    logger.info("Event rejected", extra=extra)
    return _problem(status, code, detail, trace_id, fields)


def _problem(status, code, detail, trace_id, fields=None):
    """RFC 9457 problem details, with the same `code`, `requestId` and `fields` as the Spring services."""
    problem = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
        "requestId": trace_id,
    }
    if fields:
        problem["fields"] = fields
    return _response(status, problem, trace_id, content_type="application/problem+json")


def _response(status, body, trace_id, content_type="application/json"):
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type, "X-Trace-Id": trace_id},
        "body": json.dumps(body),
    }
