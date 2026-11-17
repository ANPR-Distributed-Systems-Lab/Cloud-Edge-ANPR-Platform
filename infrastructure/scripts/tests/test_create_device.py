"""Unit tests of create_device.py. Cognito is replaced by botocore's Stubber and the HTTP calls by a fake: no network.

    pip install -r requirements.txt pytest && pytest test_create_device.py
"""

import json
import os
import string

import pytest

import api_client
import create_device
from conftest import API, POOL_ID

ACCOUNT_ID = "d1c2a0f8-0000-4000-8000-000000000000"
DEVICE_ID = "5b2f6c1e-0000-4000-8000-000000000001"
CREATED = {"deviceId": DEVICE_ID, "accountId": ACCOUNT_ID, "username": "rpi-01", "createdAt": "2026-11-14T08:00:00Z"}
ADMIN_DEVICES = "/api/v1/admin/devices"


def run(argv, environment, monkeypatch):
    monkeypatch.setattr(create_device, "open_environment", lambda profile, terraform_dir: environment)
    create_device.run(create_device.parse_args(argv))


def sent_password(fake_api):
    return fake_api.requests[0].body["password"]


# ---------------------------------------------------------------- password


def test_generated_passwords_meet_the_policy_of_the_pool():
    for _ in range(200):
        password = create_device.generate_password()
        assert len(password) >= 12
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        assert any(c in "!#%*+-=?_" for c in password)


def test_generated_passwords_differ():
    assert len({create_device.generate_password() for _ in range(50)}) == 50


# ---------------------------------------------------------------- creating a device


def test_creates_the_device_writes_the_file_and_never_prints_the_password(environment, fake_api, monkeypatch, tmp_path, capsys):
    fake_api.answer("POST", ADMIN_DEVICES, 201, CREATED)
    out = tmp_path / "device-credentials.json"

    run(["--account-id", ACCOUNT_ID, "--out", str(out)], environment, monkeypatch)

    request = fake_api.requests[0]
    assert request.signed and request.url == f"{API}{ADMIN_DEVICES}"
    assert request.body == {"accountId": ACCOUNT_ID, "username": "rpi-01", "password": sent_password(fake_api)}
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8")) == {"username": "rpi-01", "password": sent_password(fake_api)}
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o600

    printed = capsys.readouterr()
    assert sent_password(fake_api) not in printed.out + printed.err
    for shown in (DEVICE_ID, ACCOUNT_ID, "rpi-01", str(out.resolve()), "docker compose cp", "/config/device-credentials.json"):
        assert shown in printed.out


def test_the_person_is_found_by_username(environment, cognito, fake_api, monkeypatch, tmp_path):
    _, stub = cognito
    stub.add_response("admin_get_user", {"Username": "alice", "UserAttributes": [{"Name": "sub", "Value": ACCOUNT_ID}]},
                      {"UserPoolId": POOL_ID, "Username": "alice"})
    fake_api.answer("POST", ADMIN_DEVICES, 201, CREATED)

    run(["--person-username", "alice", "--device-username", "rpi-02", "--out", str(tmp_path / "c.json")], environment, monkeypatch)

    assert fake_api.requests[0].body["accountId"] == ACCOUNT_ID
    assert fake_api.requests[0].body["username"] == "rpi-02"


def test_an_unknown_person_is_reported_and_nothing_is_created(environment, cognito, fake_api, monkeypatch, tmp_path):
    _, stub = cognito
    stub.add_client_error("admin_get_user", service_error_code="UserNotFoundException")

    with pytest.raises(api_client.PlatformError, match="No user alice"):
        run(["--person-username", "alice", "--out", str(tmp_path / "c.json")], environment, monkeypatch)
    assert fake_api.requests == []


# ---------------------------------------------------------------- the file


def test_refuses_to_write_inside_the_repository(environment, fake_api, monkeypatch):
    inside = create_device.REPOSITORY_ROOT / "infrastructure" / "device-credentials.json"

    with pytest.raises(api_client.PlatformError, match="inside the repository"):
        run(["--account-id", ACCOUNT_ID, "--out", str(inside)], environment, monkeypatch)
    assert fake_api.requests == []
    assert not inside.exists()


def test_refuses_a_path_that_leads_into_the_repository_through_dots(environment, fake_api, monkeypatch):
    sneaky = create_device.REPOSITORY_ROOT / "docs" / ".." / "credentials.json"

    with pytest.raises(api_client.PlatformError, match="inside the repository"):
        run(["--account-id", ACCOUNT_ID, "--out", str(sneaky)], environment, monkeypatch)
    assert fake_api.requests == []


def test_refuses_to_overwrite_without_force(environment, fake_api, monkeypatch, tmp_path):
    out = tmp_path / "c.json"
    out.write_text("old")

    with pytest.raises(api_client.PlatformError, match="--force"):
        run(["--account-id", ACCOUNT_ID, "--out", str(out)], environment, monkeypatch)
    assert out.read_text() == "old"
    assert fake_api.requests == []


def test_force_overwrites(environment, fake_api, monkeypatch, tmp_path):
    out = tmp_path / "c.json"
    out.write_text("old")
    fake_api.answer("POST", ADMIN_DEVICES, 201, CREATED)

    run(["--account-id", ACCOUNT_ID, "--out", str(out), "--force"], environment, monkeypatch)

    assert json.loads(out.read_text())["username"] == "rpi-01"


def test_a_missing_directory_is_reported_before_the_device_is_created(environment, fake_api, monkeypatch, tmp_path):
    with pytest.raises(api_client.PlatformError, match="does not exist"):
        run(["--account-id", ACCOUNT_ID, "--out", str(tmp_path / "nope" / "c.json")], environment, monkeypatch)
    assert fake_api.requests == []


def test_a_file_that_cannot_be_written_deletes_the_device_again(environment, fake_api, monkeypatch, tmp_path):
    fake_api.answer("POST", ADMIN_DEVICES, 201, CREATED)
    fake_api.answer("DELETE", f"{ADMIN_DEVICES}/{DEVICE_ID}", 204)

    def refuse(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(create_device, "write_credentials", refuse)

    with pytest.raises(api_client.PlatformError, match="deleted again") as error:
        run(["--account-id", ACCOUNT_ID, "--out", str(tmp_path / "c.json")], environment, monkeypatch)

    assert [r.method for r in fake_api.requests] == ["POST", "DELETE"]
    assert sent_password(fake_api) not in str(error.value)


# ---------------------------------------------------------------- error mapping


@pytest.mark.parametrize("status, body, expected", [
    (400, {"code": "VALIDATION_FAILED", "requestId": "r-1", "fields": [{"field": "password", "code": "PASSWORD_POLICY"}]},
     "password PASSWORD_POLICY"),
    (403, {"message": "Forbidden"}, "refused the signature"),
    (404, {"code": "ACCOUNT_NOT_FOUND", "requestId": "r-1"}, "not a person"),
    (409, {"code": "USERNAME_TAKEN", "requestId": "r-1"}, "another --device-username"),
    (409, {"code": "ACCOUNT_HAS_DEVICE", "requestId": "r-1"}, "--delete"),
    (500, {"code": "INTERNAL_ERROR", "requestId": "r-1"}, "answered 500"),
])
def test_error_answers_become_clear_messages_without_the_password(environment, fake_api, monkeypatch, tmp_path, status, body, expected):
    fake_api.answer("POST", ADMIN_DEVICES, status, body)
    out = tmp_path / "c.json"

    with pytest.raises(api_client.PlatformError) as error:
        run(["--account-id", ACCOUNT_ID, "--out", str(out)], environment, monkeypatch)

    assert expected in str(error.value)
    assert sent_password(fake_api) not in str(error.value)
    assert not out.exists()


def test_an_answer_that_is_not_json_is_still_reported(environment, fake_api, monkeypatch, tmp_path):
    fake_api.answers[("POST", ADMIN_DEVICES)] = (403, "<html>denied</html>")

    with pytest.raises(api_client.PlatformError, match="refused the signature"):
        run(["--account-id", ACCOUNT_ID, "--out", str(tmp_path / "c.json")], environment, monkeypatch)


def test_missing_aws_credentials_are_reported(environment, monkeypatch, tmp_path):
    environment.session.get_credentials = lambda: None

    with pytest.raises(api_client.PlatformError, match="No AWS credentials"):
        run(["--account-id", ACCOUNT_ID, "--out", str(tmp_path / "c.json")], environment, monkeypatch)


def test_main_exits_with_1_and_prints_the_message_on_stderr(environment, monkeypatch, capsys):
    monkeypatch.setattr(create_device, "open_environment", lambda profile, terraform_dir: environment)
    inside = create_device.REPOSITORY_ROOT / "c.json"

    with pytest.raises(SystemExit) as exit_info:
        create_device.main(["--account-id", ACCOUNT_ID, "--out", str(inside)])

    assert exit_info.value.code == 1
    assert "inside the repository" in capsys.readouterr().err


# ---------------------------------------------------------------- deleting a device


def test_delete_calls_the_admin_route_signed(environment, fake_api, monkeypatch, capsys):
    fake_api.answer("DELETE", f"{ADMIN_DEVICES}/{DEVICE_ID}", 204)

    run(["--delete", DEVICE_ID], environment, monkeypatch)

    request = fake_api.requests[0]
    assert (request.method, request.url, request.signed) == ("DELETE", f"{API}{ADMIN_DEVICES}/{DEVICE_ID}", True)
    assert DEVICE_ID in capsys.readouterr().out


def test_delete_of_an_unknown_device_is_reported(environment, fake_api, monkeypatch):
    fake_api.answer("DELETE", f"{ADMIN_DEVICES}/{DEVICE_ID}", 404, {"code": "DEVICE_NOT_FOUND", "requestId": "r-1"})

    with pytest.raises(api_client.PlatformError, match="No such device"):
        run(["--delete", DEVICE_ID], environment, monkeypatch)


# ---------------------------------------------------------------- arguments


@pytest.mark.parametrize("argv", [
    [],
    ["--out", "c.json"],
    ["--account-id", ACCOUNT_ID],
    ["--account-id", ACCOUNT_ID, "--person-username", "alice", "--out", "c.json"],
    ["--delete", DEVICE_ID, "--out", "c.json"],
    ["--account-id", "not-a-uuid", "--out", "c.json"],
    ["--account-id", ACCOUNT_ID, "--out", "c.json", "--device-username", "Bad_Name"],
    ["--account-id", ACCOUNT_ID, "--out", "c.json", "--device-username", "ab"],
    ["--delete", "not-a-uuid"],
])
def test_invalid_arguments_are_refused(argv):
    with pytest.raises(SystemExit) as exit_info:
        create_device.parse_args(argv)
    assert exit_info.value.code == 2
