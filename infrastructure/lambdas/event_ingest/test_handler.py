"""Unit tests of the ingest Lambda. SNS is replaced by botocore's Stubber: no AWS access, and any
publish call that a test did not expect fails the test."""

import base64
import importlib
import json

import pytest
from botocore.stub import Stubber

TOPIC_ARN = "arn:aws:sns:eu-central-1:123456789012:anpr-dev-edge-events"
ROUTE = "POST /api/v1/ingest/detections"
REQUEST_ID = "api-gateway-request-id"


@pytest.fixture
def ingest(monkeypatch):
    """The handler module, imported with the environment Terraform gives the function."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setenv("EVENT_TYPE_BY_ROUTE", json.dumps({ROUTE: "detection"}))
    import handler

    return importlib.reload(handler)  # re-read the environment for every test


@pytest.fixture
def sns(ingest):
    with Stubber(ingest.sns) as stub:
        yield stub
        stub.assert_no_pending_responses()


def api_event(body, route=ROUTE, headers=None, base64_encoded=False):
    """A minimal API Gateway HTTP API event (payload format 2.0)."""
    return {
        "routeKey": route,
        "headers": headers or {},
        "body": body,
        "isBase64Encoded": base64_encoded,
        "requestContext": {"requestId": REQUEST_ID},
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
            },
        },
    )


# ---------------------------------------------------------------- accepted events


def test_publishes_the_body_unchanged_with_event_type_and_client_trace_id(ingest, sns):
    body = '{"deviceId": "d-1", "detections": [{"plate": "WA12345"}]}'
    expect_publish(sns, body, trace_id="trace-from-device")

    response = ingest.handler(api_event(body, headers={"x-trace-id": "trace-from-device"}), None)

    assert response["statusCode"] == 202
    assert json.loads(response["body"]) == {"messageId": "message-1", "traceId": "trace-from-device"}
    assert response["headers"]["X-Trace-Id"] == "trace-from-device"


@pytest.mark.parametrize("header", [None, "has spaces", "x" * 65, "semi;colon"])
def test_uses_the_api_gateway_request_id_when_the_client_trace_id_is_missing_or_unsafe(ingest, sns, header):
    expect_publish(sns, "[]")
    headers = {} if header is None else {"x-trace-id": header}

    response = ingest.handler(api_event("[]", headers=headers), None)

    assert response["headers"]["X-Trace-Id"] == REQUEST_ID


def test_decodes_base64_encoded_bodies(ingest, sns):
    body = '{"deviceId": "d-1"}'
    expect_publish(sns, body)

    response = ingest.handler(api_event(base64.b64encode(body.encode()).decode(), base64_encoded=True), None)

    assert response["statusCode"] == 202


# ---------------------------------------------------------------- rejected requests (nothing is published)


@pytest.mark.parametrize("body", ["", "not json", '"a string"', "42", "null"])
def test_rejects_bodies_that_are_not_a_json_object_or_array(ingest, sns, body):
    response = ingest.handler(api_event(body), None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["code"] == "INVALID_JSON"


def test_rejects_invalid_base64(ingest, sns):
    response = ingest.handler(api_event("not base64!", base64_encoded=True), None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["code"] == "INVALID_BODY"


def test_rejects_bodies_larger_than_an_sns_message(ingest, sns):
    too_large = json.dumps({"padding": "x" * ingest.MAX_BODY_BYTES})

    response = ingest.handler(api_event(too_large), None)

    assert response["statusCode"] == 413


def test_rejects_routes_without_an_event_type(ingest, sns):
    response = ingest.handler(api_event("{}", route="POST /api/v1/ingest/unknown"), None)

    assert response["statusCode"] == 404


def test_problem_responses_follow_rfc_9457_and_carry_the_trace_id(ingest, sns):
    response = ingest.handler(api_event("not json"), None)

    assert response["headers"]["Content-Type"] == "application/problem+json"
    problem = json.loads(response["body"])
    assert problem["status"] == 400
    assert problem["title"] == "Bad Request"
    assert problem["requestId"] == REQUEST_ID


# ---------------------------------------------------------------- SNS failure


def test_answers_503_so_the_device_retries_when_sns_fails(ingest, sns):
    sns.add_client_error("publish", service_error_code="InternalError", http_status_code=500)

    response = ingest.handler(api_event("{}"), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["code"] == "PUBLISH_FAILED"
