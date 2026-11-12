"""Cognito sign-in of the device and the Api wrapper, against scripted HTTP answers (no AWS)."""
import json

import pytest
from fakes import FakeHttp, response

from detection.cloud.api import Api
from detection.cloud.cognito import AuthError, CognitoAuth
from detection.cloud.transport import NetworkError

BASE = "https://abc.execute-api.eu-central-1.amazonaws.com"


def tokens(access="access-1", expires=3600, refresh="refresh-1"):
    result = {"AccessToken": access, "ExpiresIn": expires, "TokenType": "Bearer", "IdToken": "id"}
    if refresh:
        result["RefreshToken"] = refresh
    return response(200, {"AuthenticationResult": result})


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / "device-credentials.json"
    path.write_text(json.dumps({"username": "rpi-01", "password": "secret-pw"}))
    return path


def auth_with(http, credentials, now):
    return CognitoAuth("eu-central-1", "client-123", credentials, http, clock=lambda: now[0])


def test_sign_in_uses_the_password_flow_of_the_public_client(credentials):
    http = FakeHttp(tokens())
    assert auth_with(http, credentials, [0.0]).token() == "access-1"
    [sent] = http.requests
    assert sent["url"] == "https://cognito-idp.eu-central-1.amazonaws.com/"
    assert sent["headers"]["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert sent["headers"]["Content-Type"] == "application/x-amz-json-1.1"
    assert sent["body"] == {"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": "client-123",
                            "AuthParameters": {"USERNAME": "rpi-01", "PASSWORD": "secret-pw"}}


def test_the_token_is_reused_then_renewed_with_the_refresh_token(credentials):
    now = [0.0]
    http = FakeHttp(tokens(), tokens(access="access-2", refresh=None))
    auth = auth_with(http, credentials, now)
    auth.token()
    now[0] = 3000.0
    assert auth.token() == "access-1" and len(http.requests) == 1
    now[0] = 3500.0  # within RENEW_BEFORE_SECONDS of the expiry
    assert auth.token() == "access-2"
    assert http.requests[1]["body"]["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert http.requests[1]["body"]["AuthParameters"] == {"REFRESH_TOKEN": "refresh-1"}


def test_a_refused_refresh_token_falls_back_to_the_password(credentials):
    http = FakeHttp(tokens(), response(400, {"__type": "NotAuthorizedException", "message": "expired"}),
                    tokens(access="access-3"))
    auth = auth_with(http, credentials, [0.0])
    auth.token()
    auth.invalidate()
    assert auth.token() == "access-3"
    assert [r["body"]["AuthFlow"] for r in http.requests] == ["USER_PASSWORD_AUTH", "REFRESH_TOKEN_AUTH",
                                                              "USER_PASSWORD_AUTH"]


def test_wrong_password_and_missing_credentials_raise_auth_error(credentials, tmp_path):
    http = FakeHttp(response(400, {"__type": "NotAuthorizedException", "message": "Incorrect username or password."}))
    with pytest.raises(AuthError, match="NotAuthorizedException"):
        auth_with(http, credentials, [0.0]).token()
    with pytest.raises(AuthError, match="credentials"):
        auth_with(FakeHttp(), tmp_path / "missing.json", [0.0]).token()


def test_no_network_is_an_auth_error(credentials):
    with pytest.raises(AuthError):
        auth_with(FakeHttp(NetworkError("timeout")), credentials, [0.0]).token()


class StubAuth:
    def __init__(self):
        self.issued, self.invalidated = 0, 0

    def token(self):
        self.issued += 1
        return f"token-{self.issued}"

    def invalidate(self):
        self.invalidated += 1


def test_api_sends_the_token_and_trace_id_to_the_platform_only():
    http = FakeHttp(response(202), response(202))
    api = Api(http, StubAuth(), BASE)
    api.request("POST", BASE + "/api/v1/ingest/detections", trace_id="t-1", body={})
    api.request("POST", "http://localhost:8200/api/v1/ingest/detections", trace_id="t-2", body={})
    assert http.requests[0]["headers"] == {"X-Trace-Id": "t-1", "Authorization": "Bearer token-1"}
    assert http.requests[1]["headers"] == {"X-Trace-Id": "t-2"}  # a mock never sees the token


def test_api_renews_the_token_once_after_a_401():
    auth = StubAuth()
    http = FakeHttp(response(401), response(202))
    assert Api(http, auth, BASE).request("GET", BASE + "/api/v1/device/config", trace_id="t").status == 202
    assert auth.invalidated == 1
    assert [r["headers"]["Authorization"] for r in http.requests] == ["Bearer token-1", "Bearer token-2"]


def test_api_without_auth_sends_no_token():
    http = FakeHttp(response(200))
    Api(http, None, BASE).request("GET", BASE + "/api/v1/device/config", trace_id="t")
    assert "Authorization" not in http.requests[0]["headers"]
