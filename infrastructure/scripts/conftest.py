"""Fixtures shared by the tests of create_device.py and check_platform.py: a stubbed Cognito and a fake platform API."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from botocore.stub import Stubber

import api_client

API = "https://api.example.test"
POOL_ID = "eu-central-1_test"
WEB_CLIENT_ID = "web-client-id"


@pytest.fixture
def cognito():
    client = boto3.client("cognito-idp", region_name="eu-central-1", aws_access_key_id="test", aws_secret_access_key="test")
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


@pytest.fixture
def environment(cognito):
    client, _ = cognito
    session = SimpleNamespace(client=lambda service: client, get_credentials=lambda: object())
    return api_client.Environment(API, "eu-central-1", POOL_ID, WEB_CLIENT_ID, session)


class FakeApi:
    """Replaces the HTTP calls: records every request and answers from the table filled with answer()."""

    def __init__(self):
        self.requests = []
        self.answers = {}

    def answer(self, method, path, status, body=None):
        self.answers[(method, path)] = (status, "" if body is None else json.dumps(body))

    def call(self, method, url, token=None, body=None):
        return self.record(method, url, token, body, signed=False)

    def signed_call(self, session, region, method, url, body=None):
        return self.record(method, url, None, body, signed=True)

    def record(self, method, url, token, body, signed):
        parts = urlsplit(url)
        request = SimpleNamespace(method=method, url=url, path=parts.path, query=parse_qs(parts.query), token=token,
                                  body=body, signed=signed)
        self.requests.append(request)
        return self.answers[(method, parts.path)]


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(api_client, "call", api.call)
    monkeypatch.setattr(api_client, "signed_call", api.signed_call)
    return api
