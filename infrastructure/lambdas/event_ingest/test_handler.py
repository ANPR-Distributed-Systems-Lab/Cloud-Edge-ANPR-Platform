"""Unit tests of the ingest Lambda. SNS is replaced by botocore's Stubber: no AWS access, and any
publish call that a test did not expect fails the test."""

import base64
import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from botocore.stub import Stubber

TOPIC_ARN = "arn:aws:sns:eu-central-1:123456789012:anpr-dev-edge-events"
DETECTIONS_ROUTE = "POST /api/v1/ingest/detections"
LOCATIONS_ROUTE = "POST /api/v1/ingest/device-locations"
REQUEST_ID = "api-gateway-request-id"
DEVICE_ID = "a1b2c3d4-5678-90ab-cdef-111111111111"
OTHER_DEVICE_ID = "f0e1d2c3-5678-90ab-cdef-222222222222"
DEVICE_CLAIMS = {"sub": DEVICE_ID, "account_type": "device"}
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
BATCH_ID = "0192f3a4-7c1e-7b2a-9d41-5f3e8a1c2b10"


def stamp(moment):
    """RFC 3339 UTC with milliseconds, as the edge sends it."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def detection(number=1, **overrides):
    item = {
        "detectionId": f"0192f3a4-7c1f-7e11-8a02-{number:012d}",
        "frameId": "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c",
        "detectedAt": stamp(NOW - timedelta(minutes=1)),
        "plate": "WA12345",
        "ocrConfidence": 0.94,
        "detectorConfidence": 0.88,
        "imageKey": f"images/{DEVICE_ID}/2026/11/02/0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c.jpg",
        "corners": [[0.412, 0.531], [0.447, 0.529], [0.448, 0.548], [0.413, 0.551]],
        "location": {"lat": 52.229676, "lon": 21.012229, "accuracyM": 4.5, "fixAgeMs": 300},
    }
    item.update(overrides)
    return item


def location(number=1, **overrides):
    item = {
        "locationId": f"0192f3a4-9a11-7d20-9c01-{number:012d}",
        "recordedAt": stamp(NOW - timedelta(seconds=30)),
        "lat": 52.229676,
        "lon": 21.012229,
        "accuracyM": 4.5,
        "speedMps": 13.9,
        "headingDeg": 87.0,
    }
    item.update(overrides)
    return item


def detections_batch(*items):
    return {"batchId": BATCH_ID, "detections": list(items) or [detection()]}


def locations_batch(*items):
    return {"batchId": BATCH_ID, "locations": list(items) or [location()]}


@pytest.fixture
def ingest(monkeypatch):
    """The handler module, imported with the environment Terraform gives the function, at a fixed time."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setenv(
        "EVENT_TYPE_BY_ROUTE", json.dumps({DETECTIONS_ROUTE: "detection", LOCATIONS_ROUTE: "device-location"})
    )
    import handler

    module = importlib.reload(handler)  # re-read the environment for every test
    monkeypatch.setattr(module, "_now", lambda: NOW)
    return module


@pytest.fixture
def sns(ingest):
    with Stubber(ingest.sns) as stub:
        yield stub
        stub.assert_no_pending_responses()


def api_event(body, route=DETECTIONS_ROUTE, headers=None, base64_encoded=False, claims=DEVICE_CLAIMS):
    """A minimal API Gateway HTTP API event (payload format 2.0) of a device that passed the JWT authorizer."""
    if not isinstance(body, str):
        body = json.dumps(body)
    return {
        "routeKey": route,
        "headers": {"content-type": "application/json"} if headers is None else headers,
        "body": body,
        "isBase64Encoded": base64_encoded,
        "requestContext": {"requestId": REQUEST_ID, "authorizer": {"jwt": {"claims": claims}}},
    }


def expect_publish(sns, message, event_type="detection", trace_id=REQUEST_ID):
    sns.add_response(
        "publish",
        {"MessageId": "message-1"},
        expected_params={
            "TopicArn": TOPIC_ARN,
            "Message": message,
            "MessageAttributes": {
                "eventType": {"DataType": "String", "StringValue": event_type},
                "traceId": {"DataType": "String", "StringValue": trace_id},
                "deviceId": {"DataType": "String", "StringValue": DEVICE_ID},
            },
        },
    )


def problem_of(response):
    return json.loads(response["body"])


def validation_errors(ingest, body, route=DETECTIONS_ROUTE):
    """The fields[] of a request that must be refused with VALIDATION_FAILED (the sns fixture forbids publishing)."""
    response = ingest.handler(api_event(body, route=route), None)
    assert response["statusCode"] == 400
    problem = problem_of(response)
    assert problem["code"] == "VALIDATION_FAILED"
    return problem["fields"]


# ---------------------------------------------------------------- accepted batches


def test_publishes_a_valid_detection_batch_unchanged_and_answers_with_the_batch(ingest, sns):
    body = json.dumps(detections_batch(detection(1), detection(2, extraField="kept")))
    expect_publish(sns, body, trace_id="trace-from-device")

    response = ingest.handler(
        api_event(body, headers={"content-type": "application/json", "x-trace-id": "trace-from-device"}), None
    )

    assert response["statusCode"] == 202
    assert json.loads(response["body"]) == {"batchId": BATCH_ID, "accepted": 2, "traceId": "trace-from-device"}
    assert response["headers"]["X-Trace-Id"] == "trace-from-device"


def test_publishes_a_valid_location_batch_as_device_location_events(ingest, sns):
    body = json.dumps(locations_batch(location(1), location(2, accuracyM=None, speedMps=None, headingDeg=None)))
    expect_publish(sns, body, event_type="device-location")

    response = ingest.handler(api_event(body, route=LOCATIONS_ROUTE), None)

    assert response["statusCode"] == 202
    assert json.loads(response["body"])["accepted"] == 2


def test_accepts_optional_location_fields_missing_and_tolerated_clock_skew(ingest, sns):
    item = detection(detectedAt=stamp(NOW + timedelta(minutes=4)), location={"lat": 52.2, "lon": 21.0})
    body = json.dumps(detections_batch(item))
    expect_publish(sns, body)

    assert ingest.handler(api_event(body), None)["statusCode"] == 202


@pytest.mark.parametrize("header", [None, "has spaces", "x" * 65, "semi;colon"])
def test_uses_the_api_gateway_request_id_when_the_client_trace_id_is_missing_or_unsafe(ingest, sns, header):
    body = json.dumps(detections_batch())
    expect_publish(sns, body)
    headers = {"content-type": "application/json"}
    if header is not None:
        headers["x-trace-id"] = header

    response = ingest.handler(api_event(body, headers=headers), None)

    assert response["headers"]["X-Trace-Id"] == REQUEST_ID


def test_decodes_base64_encoded_bodies(ingest, sns):
    body = json.dumps(detections_batch())
    expect_publish(sns, body)

    response = ingest.handler(api_event(base64.b64encode(body.encode()).decode(), base64_encoded=True), None)

    assert response["statusCode"] == 202


def test_accepts_a_content_type_with_a_charset(ingest, sns):
    body = json.dumps(detections_batch())
    expect_publish(sns, body)

    response = ingest.handler(api_event(body, headers={"content-type": "application/json; charset=utf-8"}), None)

    assert response["statusCode"] == 202


# ---------------------------------------------------------------- rejected requests (nothing is published)


@pytest.mark.parametrize(
    "claims",
    [
        None,  # the route has no authorizer
        {"sub": DEVICE_ID},  # no account type
        {"sub": DEVICE_ID, "account_type": "user"},  # a person, not a device
        {"account_type": "device"},  # no id
        {"sub": "", "account_type": "device"},
    ],
)
def test_rejects_requests_whose_token_is_not_a_device_token(ingest, sns, claims):
    event = api_event(detections_batch(), claims=claims)
    if claims is None:
        del event["requestContext"]["authorizer"]

    response = ingest.handler(event, None)

    assert response["statusCode"] == 403
    assert problem_of(response)["code"] == "FORBIDDEN"


@pytest.mark.parametrize("headers", [{}, {"content-type": "text/plain"}, {"content-type": "application/xml"}])
def test_rejects_bodies_that_are_not_declared_as_json(ingest, sns, headers):
    response = ingest.handler(api_event(detections_batch(), headers=headers), None)

    assert response["statusCode"] == 415
    assert problem_of(response)["code"] == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.parametrize("body", ["", "not json", '"a string"', "42", "null", "[]", '{"batchId": NaN}'])
def test_rejects_bodies_that_are_not_a_json_object(ingest, sns, body):
    response = ingest.handler(api_event(body), None)

    assert response["statusCode"] == 400
    assert problem_of(response)["code"] == "INVALID_JSON"


def test_rejects_invalid_base64(ingest, sns):
    response = ingest.handler(api_event("not base64!", base64_encoded=True), None)

    assert response["statusCode"] == 400
    assert problem_of(response)["code"] == "INVALID_BODY"


def test_rejects_bodies_larger_than_an_sns_message(ingest, sns):
    too_large = json.dumps({"padding": "x" * ingest.MAX_BODY_BYTES})

    response = ingest.handler(api_event(too_large), None)

    assert response["statusCode"] == 413


def test_rejects_routes_without_an_event_type(ingest, sns):
    response = ingest.handler(api_event(detections_batch(), route="POST /api/v1/ingest/unknown"), None)

    assert response["statusCode"] == 404


def test_problem_responses_follow_rfc_9457_and_carry_the_trace_id(ingest, sns):
    response = ingest.handler(api_event("not json"), None)

    assert response["headers"]["Content-Type"] == "application/problem+json"
    problem = problem_of(response)
    assert problem["status"] == 400
    assert problem["title"] == "Bad Request"
    assert problem["requestId"] == REQUEST_ID
    assert "fields" not in problem


def test_refuses_to_start_when_an_event_type_has_no_validator(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setenv("EVENT_TYPE_BY_ROUTE", json.dumps({"POST /api/v1/ingest/other": "other"}))
    import handler

    with pytest.raises(RuntimeError, match="other"):
        importlib.reload(handler)


# ---------------------------------------------------------------- validation of detections


def with_detection_change(change):
    """A valid batch of one detection, changed by `change` (a function mutating the detection)."""
    batch = detections_batch()
    change(batch["detections"][0])
    return batch


@pytest.mark.parametrize(
    "change, field, code",
    [
        (lambda d: d.pop("detectionId"), "detections[0].detectionId", "REQUIRED"),
        (lambda d: d.update(detectionId="not-a-uuid"), "detections[0].detectionId", "FORMAT"),
        (lambda d: d.update(frameId=42), "detections[0].frameId", "FORMAT"),
        (lambda d: d.update(detectedAt="2026-11-02 11:59:00"), "detections[0].detectedAt", "FORMAT"),
        (lambda d: d.update(detectedAt="2026-11-02T11:59:00+01:00"), "detections[0].detectedAt", "FORMAT"),
        (lambda d: d.update(detectedAt="2026-13-02T11:59:00.000Z"), "detections[0].detectedAt", "FORMAT"),
        (lambda d: d.update(detectedAt=stamp(NOW + timedelta(minutes=6))), "detections[0].detectedAt", "TIMESTAMP_IN_FUTURE"),
        (lambda d: d.update(detectedAt=stamp(NOW - timedelta(days=31))), "detections[0].detectedAt", "TIMESTAMP_TOO_OLD"),
        (lambda d: d.pop("plate"), "detections[0].plate", "REQUIRED"),
        (lambda d: d.update(plate="wa 123"), "detections[0].plate", "PATTERN"),
        (lambda d: d.update(plate="WA"), "detections[0].plate", "PATTERN"),
        (lambda d: d.update(plate=12345), "detections[0].plate", "TYPE"),
        (lambda d: d.update(ocrConfidence=1.5), "detections[0].ocrConfidence", "RANGE"),
        (lambda d: d.update(ocrConfidence="0.9"), "detections[0].ocrConfidence", "TYPE"),
        (lambda d: d.update(detectorConfidence=True), "detections[0].detectorConfidence", "TYPE"),
        (lambda d: d.update(detectorConfidence=-0.1), "detections[0].detectorConfidence", "RANGE"),
        (lambda d: d.update(imageKey="photos/a.jpg"), "detections[0].imageKey", "FORMAT"),
        (lambda d: d.update(imageKey=f"images/{DEVICE_ID}/a.jpg"), "detections[0].imageKey", "FORMAT"),
        (lambda d: d.update(imageKey=f"images/{DEVICE_ID}/2026/11/02/{d['detectionId']}.jpg"), "detections[0].imageKey", "FORMAT"),
        (lambda d: d.update(imageKey=f"images/{OTHER_DEVICE_ID}/2026/11/02/{d['frameId']}.jpg"), "detections[0].imageKey", "IMAGE_KEY_FOREIGN"),
        (lambda d: d.update(corners=[[0.4, 0.5], [0.45, 0.5], [0.45, 0.55]]), "detections[0].corners", "INVALID_CORNERS"),
        (lambda d: d.update(corners=[[0.4, 0.5], [0.4, 0.55], [0.45, 0.55], [0.45, 0.5]]), "detections[0].corners", "INVALID_CORNERS"),  # counter-clockwise
        (lambda d: d.update(corners=[[0.4, 0.5], [0.45, 0.55], [0.45, 0.5], [0.4, 0.55]]), "detections[0].corners", "INVALID_CORNERS"),  # crossed
        (lambda d: d.update(corners=[[0.4, 0.5], [0.45, 0.5], [0.5, 0.5], [0.4, 0.5]]), "detections[0].corners", "INVALID_CORNERS"),  # degenerate
        (lambda d: d.update(corners=[[0.4, 0.5], [1.2, 0.5], [1.2, 0.55], [0.4, 0.55]]), "detections[0].corners", "RANGE"),
        (lambda d: d.pop("location"), "detections[0].location", "REQUIRED"),
        (lambda d: d.update(location=[52.2, 21.0]), "detections[0].location", "TYPE"),
        (lambda d: d["location"].update(lat=91), "detections[0].location.lat", "RANGE"),
        (lambda d: d["location"].pop("lon"), "detections[0].location.lon", "REQUIRED"),
        (lambda d: d["location"].update(lat=0, lon=0), "detections[0].location", "INVALID_LOCATION"),
        (lambda d: d["location"].update(accuracyM=-1), "detections[0].location.accuracyM", "RANGE"),
        (lambda d: d["location"].update(fixAgeMs=1.5), "detections[0].location.fixAgeMs", "TYPE"),
    ],
)
def test_rejects_a_detection_that_breaks_a_rule(ingest, sns, change, field, code):
    errors = validation_errors(ingest, with_detection_change(change))

    assert {"index": 0, "field": field, "code": code} in [
        {key: error[key] for key in ("index", "field", "code")} for error in errors
    ]


@pytest.mark.parametrize(
    "batch, field, code",
    [
        ({"detections": [detection()]}, "batchId", "REQUIRED"),
        ({"batchId": "1234", "detections": [detection()]}, "batchId", "FORMAT"),
        ({"batchId": BATCH_ID}, "detections", "REQUIRED"),
        ({"batchId": BATCH_ID, "detections": {}}, "detections", "TYPE"),
        ({"batchId": BATCH_ID, "detections": []}, "detections", "SIZE"),
        ({"batchId": BATCH_ID, "detections": [detection(n) for n in range(101)]}, "detections", "SIZE"),
    ],
)
def test_rejects_a_batch_that_breaks_a_rule_without_an_item_index(ingest, sns, batch, field, code):
    errors = validation_errors(ingest, batch)

    assert {"field": field, "code": code} in [{key: error[key] for key in ("field", "code")} for error in errors]
    assert all("index" not in error for error in errors if error["field"] == field)


def test_rejects_a_detection_id_used_twice_in_the_batch(ingest, sns):
    errors = validation_errors(ingest, detections_batch(detection(1), detection(2), detection(1)))

    assert errors == [
        {
            "index": 2,
            "field": "detections[2].detectionId",
            "code": "DUPLICATE_DETECTION_ID",
            "message": "appears twice in the batch",
        }
    ]


def test_lists_every_problem_of_the_batch_and_never_the_values(ingest, sns):
    batch = detections_batch(detection(1, plate="wa 1"), detection(2), "not an object", detection(4, ocrConfidence=2))

    response = ingest.handler(api_event(batch), None)

    problem = problem_of(response)
    assert problem["detail"] == "3 validation errors, nothing was accepted"
    assert [(e["index"], e["code"]) for e in problem["fields"]] == [(0, "PATTERN"), (2, "TYPE"), (3, "RANGE")]
    assert "wa 1" not in response["body"]


# ---------------------------------------------------------------- validation of device locations


@pytest.mark.parametrize(
    "change, field, code",
    [
        (lambda l: l.update(locationId="nope"), "locations[0].locationId", "FORMAT"),
        (lambda l: l.pop("recordedAt"), "locations[0].recordedAt", "REQUIRED"),
        (lambda l: l.update(recordedAt=stamp(NOW + timedelta(minutes=10))), "locations[0].recordedAt", "TIMESTAMP_IN_FUTURE"),
        (lambda l: l.update(lon=-181), "locations[0].lon", "RANGE"),
        (lambda l: l.update(lat=0, lon=0), "locations[0]", "INVALID_LOCATION"),
        (lambda l: l.update(speedMps=-1), "locations[0].speedMps", "RANGE"),
        (lambda l: l.update(headingDeg=360), "locations[0].headingDeg", "RANGE"),
        (lambda l: l.update(accuracyM="5"), "locations[0].accuracyM", "TYPE"),
    ],
)
def test_rejects_a_location_that_breaks_a_rule(ingest, sns, change, field, code):
    batch = locations_batch()
    change(batch["locations"][0])

    errors = validation_errors(ingest, batch, route=LOCATIONS_ROUTE)

    assert {"index": 0, "field": field, "code": code} in [
        {key: error[key] for key in ("index", "field", "code")} for error in errors
    ]


def test_rejects_a_location_id_used_twice_and_batches_over_500_points(ingest, sns):
    duplicate = validation_errors(ingest, locations_batch(location(1), location(1)), route=LOCATIONS_ROUTE)
    too_many = validation_errors(ingest, locations_batch(*[location(n) for n in range(501)]), route=LOCATIONS_ROUTE)

    assert [(e["index"], e["code"]) for e in duplicate] == [(1, "DUPLICATE_LOCATION_ID")]
    assert [(e["field"], e["code"]) for e in too_many] == [("locations", "SIZE")]


# ---------------------------------------------------------------- SNS failure


def test_answers_503_so_the_device_retries_when_sns_fails(ingest, sns):
    sns.add_client_error("publish", service_error_code="InternalError", http_status_code=500)

    response = ingest.handler(api_event(detections_batch()), None)

    assert response["statusCode"] == 503
    assert problem_of(response)["code"] == "PUBLISH_FAILED"
