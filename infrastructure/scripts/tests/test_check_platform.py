"""Unit tests of check_platform.py. Cognito is replaced by botocore's Stubber and the HTTP calls by a fake: no network.

    pip install -r requirements.txt pytest && pytest test_check_platform.py
"""

import pytest

import api_client
import check_platform
from conftest import API, POOL_ID, WEB_CLIENT_ID

PASSWORD = "Pa55-word-of-the-test!"
TOKEN = "access-token-of-the-test"
PLATE = "WA12345"
DEVICE_ID = "5b2f6c1e-0000-4000-8000-000000000001"
CREDENTIALS = {"USERNAME": "alice", "PASSWORD": PASSWORD}

DEVICE = {"deviceId": DEVICE_ID, "username": "rpi-01", "createdAt": "2026-11-14T08:00:00Z", "online": True,
          "lastMetricsAt": "2026-11-14T09:00:00Z"}
CONFIGURATION = {
    "deviceId": DEVICE_ID, "version": 7, "updatedAt": "2026-11-14T08:30:00Z", "plateCooldownSeconds": 60,
    "models": {"detector": "v2", "ocr": "v3"},
    "ml": {"detectorMinConfidence": 0.4, "ocrMinConfidence": 0.8, "readableMinProbability": 0.8,
           "minPlateWidthPx": 70, "minEdgeMarginPx": 10},
}
METRICS = {"deviceId": DEVICE_ID, "metrics": [
    {"recordedAt": f"2026-11-14T09:00:0{second}Z", "cpuTemperatureC": 55.5 + second, "processingFps": 3.5,
     "queues": {"detectionsPending": 1, "locationsPending": 2, "imagesPending": 3},
     "gps": {"fix": "FIX_3D", "satellites": 9}} for second in range(2)]}
DETECTION = {"detectionId": "11111111-0000-4000-8000-000000000001", "deviceId": DEVICE_ID, "plate": PLATE,
             "detectedAt": "2026-11-14T09:01:00Z", "position": {"lat": 52.2, "lon": 21.0}, "ocrConfidence": 0.93,
             "detectorConfidence": 0.88, "imageUrl": "https://s3.example.test/image?signature=abc"}
PAGE = {"page": 0, "size": 10, "totalElements": 42, "totalPages": 5}


def sign_in_stub(stub):
    stub.add_response("initiate_auth", {"AuthenticationResult": {"AccessToken": TOKEN}},
                      {"ClientId": WEB_CLIENT_ID, "AuthFlow": "USER_PASSWORD_AUTH", "AuthParameters": CREDENTIALS})


@pytest.fixture
def signed_in(environment, cognito, monkeypatch):
    """The password comes from the environment variable, the sign-in from the stubbed Cognito."""
    monkeypatch.setenv(check_platform.PASSWORD_VARIABLE, PASSWORD)
    monkeypatch.setattr(check_platform, "open_environment", lambda profile, terraform_dir: environment)
    sign_in_stub(cognito[1])


def run(*argv):
    check_platform.run(check_platform.parse_args(["--username", "alice", *argv]))


def printed_text(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


# ---------------------------------------------------------------- sign-in


def test_signs_in_with_user_password_auth_on_the_web_client(environment, cognito):
    sign_in_stub(cognito[1])

    assert check_platform.sign_in(environment, "alice", PASSWORD) == TOKEN


def test_admin_auth_signs_in_with_the_admin_flow(environment, cognito):
    cognito[1].add_response("admin_initiate_auth", {"AuthenticationResult": {"AccessToken": TOKEN}},
                            {"UserPoolId": POOL_ID, "ClientId": WEB_CLIENT_ID, "AuthFlow": "ADMIN_USER_PASSWORD_AUTH",
                             "AuthParameters": CREDENTIALS})

    assert check_platform.sign_in(environment, "alice", PASSWORD, admin_auth=True) == TOKEN


def test_a_client_without_the_flow_gets_a_clear_message(environment, cognito):
    cognito[1].add_client_error("initiate_auth", service_error_code="InvalidParameterException",
                                service_message="USER_PASSWORD_AUTH flow not enabled for this client")

    with pytest.raises(api_client.PlatformError, match="does not allow USER_PASSWORD_AUTH") as error:
        check_platform.sign_in(environment, "alice", PASSWORD)
    assert "--admin-auth" in str(error.value) and PASSWORD not in str(error.value)


def test_a_wrong_password_is_reported_without_the_password(environment, cognito):
    cognito[1].add_client_error("initiate_auth", service_error_code="NotAuthorizedException",
                                service_message="Incorrect username or password.")

    with pytest.raises(api_client.PlatformError, match="wrong username or password") as error:
        check_platform.sign_in(environment, "alice", PASSWORD)
    assert PASSWORD not in str(error.value)


def test_a_challenge_is_reported(environment, cognito):
    cognito[1].add_response("initiate_auth", {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "s" * 20},
                            {"ClientId": WEB_CLIENT_ID, "AuthFlow": "USER_PASSWORD_AUTH", "AuthParameters": CREDENTIALS})

    with pytest.raises(api_client.PlatformError, match="NEW_PASSWORD_REQUIRED"):
        check_platform.sign_in(environment, "alice", PASSWORD)


def test_the_password_comes_from_the_environment_variable_or_the_prompt(monkeypatch):
    monkeypatch.setenv(check_platform.PASSWORD_VARIABLE, "from-env")
    assert check_platform.read_password(prompt=lambda _: "typed") == "from-env"

    monkeypatch.delenv(check_platform.PASSWORD_VARIABLE)
    assert check_platform.read_password(prompt=lambda _: "typed") == "typed"


def test_the_password_is_not_a_command_line_option():
    with pytest.raises(SystemExit):
        check_platform.parse_args(["--username", "alice", "--password", PASSWORD, "device"])


# ---------------------------------------------------------------- plates


@pytest.mark.parametrize("plate, masked", [("WA12345", "WA*****"), ("WA1", "WA*"), ("WA", "**"), ("KR1A2B3C4D", "KR********")])
def test_plates_are_masked_to_two_characters_and_the_length(plate, masked):
    assert check_platform.mask_plate(plate) == masked
    assert len(masked) == len(plate)


# ---------------------------------------------------------------- device


def test_device_reads_the_device_its_configuration_and_three_measurements(signed_in, fake_api, capsys):
    fake_api.answer("GET", "/api/v1/device", 200, DEVICE)
    fake_api.answer("GET", "/api/v1/device/config", 200, CONFIGURATION)
    fake_api.answer("GET", "/api/v1/device/metrics", 200, METRICS)

    run("device")

    assert [(r.method, r.path, r.token) for r in fake_api.requests] == [
        ("GET", "/api/v1/device", TOKEN), ("GET", "/api/v1/device/config", TOKEN), ("GET", "/api/v1/device/metrics", TOKEN)]
    assert fake_api.requests[2].query == {"limit": ["3"]}
    assert not any(r.signed for r in fake_api.requests)
    text = printed_text(capsys)
    for shown in (DEVICE_ID, "rpi-01", "online:          True", "2026-11-14T09:00:00Z", "version 7", "detector v2, ocr v3",
                  "minPlateWidthPx: 70", "ocrMinConfidence: 0.8", "FIX_3D", "d/l/i 1/2/3", "fps 3.5"):
        assert shown in text
    assert text.index("09:00:01Z") < text.index("09:00:00Z\n") or "newest first" in text
    assert PASSWORD not in text and TOKEN not in text


def test_device_without_a_device_says_so(signed_in, fake_api):
    fake_api.answer("GET", "/api/v1/device", 404, {"code": "DEVICE_NOT_FOUND", "requestId": "r-1"})

    with pytest.raises(api_client.PlatformError, match="No device is paired"):
        run("device")


def test_a_refused_token_is_reported(signed_in, fake_api):
    fake_api.answer("GET", "/api/v1/device", 401)

    with pytest.raises(api_client.PlatformError, match="refused the token") as error:
        run("device")
    assert TOKEN not in str(error.value)


# ---------------------------------------------------------------- detections


def test_detections_searches_the_newest_first_and_masks_the_plates(signed_in, fake_api, capsys):
    fake_api.answer("GET", "/api/v1/detections/search", 200, {"items": [DETECTION], "page": PAGE})

    run("detections")

    request = fake_api.requests[0]
    assert (request.url.startswith(f"{API}/api/v1/detections/search?"), request.token) == (True, TOKEN)
    assert request.query == {"size": ["10"], "sort": ["DETECTED_AT"], "direction": ["DESC"]}
    text = printed_text(capsys)
    assert "1 detections shown, 42 in total" in text
    assert "WA*****" in text and PLATE not in text
    for shown in (DETECTION["detectionId"], "2026-11-14T09:01:00Z", "ocr 0.93", "detector 0.88", "coordinates yes", "image yes"):
        assert shown in text
    assert "signature=abc" not in text and TOKEN not in text


def test_detections_shows_plates_in_full_on_request_and_takes_a_limit(signed_in, fake_api, capsys):
    fake_api.answer("GET", "/api/v1/detections/search", 200, {"items": [{**DETECTION, "imageUrl": None}], "page": PAGE})

    run("detections", "--limit", "3", "--show-plates")

    assert fake_api.requests[0].query["size"] == ["3"]
    text = printed_text(capsys)
    assert PLATE in text and "image no" in text


@pytest.mark.parametrize("limit", ["0", "1001", "x"])
def test_detections_limit_is_validated(limit):
    with pytest.raises(SystemExit):
        check_platform.parse_args(["--username", "alice", "detections", "--limit", limit])


# ---------------------------------------------------------------- alerts


def test_alert_creates_an_alert_for_the_plate(signed_in, fake_api, capsys):
    fake_api.answer("POST", "/api/v1/alerts", 201, {"alertId": "22222222-0000-4000-8000-000000000002", "plate": PLATE,
                                                    "createdAt": "2026-11-14T09:00:00Z", "version": 0})

    run("alert", PLATE, "--text", "stolen")

    request = fake_api.requests[0]
    assert (request.method, request.url, request.token) == ("POST", f"{API}/api/v1/alerts", TOKEN)
    assert request.body == {"plate": PLATE, "alertText": "stolen"}
    text = printed_text(capsys)
    assert "22222222-0000-4000-8000-000000000002" in text and "WA*****" in text and PLATE not in text


def test_alert_without_a_text_sends_only_the_plate(signed_in, fake_api):
    fake_api.answer("POST", "/api/v1/alerts", 201, {"alertId": "22222222-0000-4000-8000-000000000002"})

    run("alert", PLATE)

    assert fake_api.requests[0].body == {"plate": PLATE}


def test_a_duplicate_alert_is_reported(signed_in, fake_api):
    fake_api.answer("POST", "/api/v1/alerts", 409, {"code": "ALERT_ALREADY_EXISTS", "requestId": "r-1"})

    with pytest.raises(api_client.PlatformError, match="already has an alert"):
        run("alert", PLATE)


def test_alert_validation_errors_show_the_field_codes(signed_in, fake_api):
    fake_api.answer("POST", "/api/v1/alerts", 400, {"code": "VALIDATION_FAILED", "requestId": "r-1",
                                                    "fields": [{"field": "plate", "code": "PATTERN"}]})

    with pytest.raises(api_client.PlatformError, match="plate PATTERN"):
        run("alert", PLATE)


@pytest.mark.parametrize("plate", ["wa12345", "WA 123", "W", "WA1234567890", "WA-123"])
def test_a_plate_that_breaks_the_pattern_is_refused_locally(plate):
    with pytest.raises(SystemExit):
        check_platform.parse_args(["--username", "alice", "alert", plate])


@pytest.mark.parametrize("argv", [["alert"], ["alert", PLATE, "--list"]])
def test_alert_needs_a_plate_or_list(argv):
    with pytest.raises(SystemExit):
        check_platform.parse_args(["--username", "alice", *argv])


def test_alert_list_masks_the_plates(signed_in, fake_api, capsys):
    alert = {"alertId": "22222222-0000-4000-8000-000000000002", "plate": PLATE, "createdAt": "2026-11-14T09:00:00Z",
             "lastDetectedAt": None, "version": 0}
    fake_api.answer("GET", "/api/v1/alerts", 200, {"items": [alert], "page": PAGE})

    run("alert", "--list")

    request = fake_api.requests[0]
    assert (request.method, request.path, request.query) == ("GET", "/api/v1/alerts", {"size": ["100"]})
    text = printed_text(capsys)
    assert "1 alerts shown, 42 in total" in text and "WA*****" in text and PLATE not in text


def test_alert_list_shows_plates_in_full_on_request(signed_in, fake_api, capsys):
    fake_api.answer("GET", "/api/v1/alerts", 200, {"items": [{"alertId": "a", "plate": PLATE, "createdAt": "c"}], "page": PAGE})

    run("alert", "--list", "--show-plates")

    assert PLATE in printed_text(capsys)


# ---------------------------------------------------------------- the whole command


def test_main_exits_with_1_when_the_sign_in_is_refused(environment, cognito, monkeypatch, capsys):
    monkeypatch.setenv(check_platform.PASSWORD_VARIABLE, PASSWORD)
    monkeypatch.setattr(check_platform, "open_environment", lambda profile, terraform_dir: environment)
    cognito[1].add_client_error("initiate_auth", service_error_code="InvalidParameterException",
                                service_message="USER_PASSWORD_AUTH flow not enabled for this client")

    with pytest.raises(SystemExit) as exit_info:
        check_platform.main(["--username", "alice", "device"])

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "does not allow USER_PASSWORD_AUTH" in captured.err and PASSWORD not in captured.out + captured.err
