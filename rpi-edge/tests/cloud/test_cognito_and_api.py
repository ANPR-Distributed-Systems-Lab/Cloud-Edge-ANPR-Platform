"""Cognito sign-in of the device and the Api wrapper, against scripted HTTP answers (no AWS)."""
import json
import threading
import time

import pytest
from fakes import FakeHttp, response

from common.faults import FaultBoard
from detection.cloud.api import Api, CloudHealth
from detection.cloud.cognito import AuthError, CognitoAuth, CredentialsError
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


class SlowHttp(FakeHttp):
    """Answers after a pause, so that threads asking at the same time overlap."""

    def request(self, method, url, headers=None, body=None):
        time.sleep(0.05)
        return super().request(method, url, headers, body)


def test_threads_asking_at_once_sign_in_once(credentials):
    http = SlowHttp(tokens())  # a second sign-in would find no answer left
    auth = auth_with(http, credentials, [0.0])
    results = []
    threads = [threading.Thread(target=lambda: results.append(auth.token())) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == ["access-1"] * 5 and len(http.requests) == 1


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
    with pytest.raises(CredentialsError, match="credentials"):
        auth_with(FakeHttp(), tmp_path / "missing.json", [0.0]).token()


@pytest.mark.parametrize("answer", [NetworkError("timeout"), response(400, {"__type": "TooManyRequestsException"}),
                                    response(500, {"__type": "InternalErrorException"}), response(503)])
def test_cognito_out_of_reach_or_failing_is_no_answer_not_a_refusal(credentials, answer):
    with pytest.raises(NetworkError):
        auth_with(FakeHttp(answer), credentials, [0.0]).token()


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
    api = Api(http, StubAuth(), BASE, FaultBoard())
    api.request("POST", BASE + "/api/v1/ingest/detections", trace_id="t-1", body={})
    api.request("POST", "http://localhost:8200/api/v1/ingest/detections", trace_id="t-2", body={})
    assert http.requests[0]["headers"] == {"X-Trace-Id": "t-1", "Authorization": "Bearer token-1"}
    assert http.requests[1]["headers"] == {"X-Trace-Id": "t-2"}  # a mock never sees the token


def test_api_renews_the_token_once_after_a_401():
    auth = StubAuth()
    http = FakeHttp(response(401), response(202))
    api = Api(http, auth, BASE, FaultBoard())
    assert api.request("GET", BASE + "/api/v1/device/config", trace_id="t").status == 202
    assert auth.invalidated == 1
    assert [r["headers"]["Authorization"] for r in http.requests] == ["Bearer token-1", "Bearer token-2"]


def test_api_without_auth_sends_no_token():
    http = FakeHttp(response(200))
    Api(http, None, BASE, FaultBoard()).request("GET", BASE + "/api/v1/device/config", trace_id="t")
    assert "Authorization" not in http.requests[0]["headers"]


@pytest.mark.parametrize(("error", "code"), [(AuthError("NotAuthorizedException"), "sign_in_refused"),
                                             (CredentialsError("no file"), "no_credentials")])
def test_a_refused_sign_in_is_a_fault_until_a_token_works(error, code):
    class Refusing(StubAuth):
        def token(self):
            raise error

    url, faults = BASE + "/api/v1/device/config", FaultBoard()
    api = Api(FakeHttp(response(200)), Refusing(), BASE, faults)
    with pytest.raises(AuthError):
        api.request("GET", url, trace_id="t")
    assert api.health.sign_in_failed and api.health.online is False and [f.code for f in faults.active()] == [code]
    api.auth = StubAuth()
    api.request("GET", url, trace_id="t")
    assert not api.health.sign_in_failed and faults.active() == []


@pytest.mark.parametrize(("answer", "code", "denied"), [
    (response(401), "token_refused", True),
    (response(403, {"code": "FORBIDDEN"}), "not_device_token", True),
    (response(403, {"code": "DEVICE_NOT_PAIRED"}), "no_owner", False),
    (response(404, {"code": "DEVICE_NOT_FOUND"}), "device_not_found", False)])
def test_an_answer_shows_the_fault_of_the_account_until_the_endpoint_answers_again(answer, code, denied):
    url, faults = BASE + "/api/v1/device/config", FaultBoard()
    retried = [response(401)] if answer.status == 401 else []  # a 401 is retried once with a renewed token
    api = Api(FakeHttp(answer, *retried, response(200)), StubAuth(), BASE, faults)
    api.request("GET", url, trace_id="t")
    assert [f.code for f in faults.active()] == [code] and api.health.denied is denied and api.health.online
    api.request("GET", url, trace_id="t")
    assert faults.active() == [] and not api.health.denied


def test_a_fault_another_endpoint_still_shows_stays():
    faults = FaultBoard()
    gone = response(404, {"code": "DEVICE_NOT_FOUND"})
    api = Api(FakeHttp(gone, gone, response(200)), StubAuth(), BASE, faults)
    api.request("GET", BASE + "/api/v1/device/config", trace_id="t")
    api.request("GET", BASE + "/api/v1/device/models", trace_id="t")
    api.request("GET", BASE + "/api/v1/device/config", trace_id="t")
    assert [f.code for f in faults.active()] == ["device_not_found"]  # the models endpoint still says so


def test_a_server_error_is_no_fault_of_the_account():
    faults = FaultBoard()
    Api(FakeHttp(response(503)), StubAuth(), BASE, faults).request("GET", BASE + "/api/v1/alerts", trace_id="t")
    assert faults.active() == []


def test_cloud_health_follows_the_latest_request():
    assert CloudHealth().online is None
    assert CloudHealth(last_answer_at=5.0, last_failure_at=3.0).online is True
    assert CloudHealth(last_answer_at=5.0, last_failure_at=6.0).online is False
