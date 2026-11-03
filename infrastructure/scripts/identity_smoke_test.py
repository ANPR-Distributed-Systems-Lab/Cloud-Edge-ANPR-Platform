"""Smoke test of the identity model on a deployed environment (docs/identity-and-access.md).

    python identity_smoke_test.py [--profile dev] [--terraform-dir infrastructure/envs/dev]

Creates one test person (group "users") and one test device (group "devices") in the user pool and
checks with their real tokens:

  tokens   the access tokens carry the claim account_type ("user" / "device") and their app client
  ingest   a valid batch with a device token is accepted (202) and the event reaches the operations queue
           with the attributes eventType and deviceId and without accountId; an invalid batch is refused
           (400 VALIDATION_FAILED); a person's token and a request without a token are refused (401)
  alerts   both kinds of tokens may list alerts, only a person's may create them
  device   device-management routes let in the right kind of token only (person: edit configuration,
           metrics chart; device: report metrics, upload URLs; both: device and configuration)
  admin    the admin routes refuse an unsigned request (403) and let a signed one reach the service
           (a DELETE of a random device id: nothing is deleted)

It never gets further than the gateway for the service routes, so it works while the services have no
running tasks (the gateway then answers 500 or 503, which still proves the caller was let in).

Whatever happens, the script deletes the two test users and the one message it published (only that
message: other messages in the queue are left alone). If operations-service is running, it may consume
the test message before the script reads it; the queue check then fails with "not found".

Passwords are generated for the run and tokens are read, but neither is ever printed.

The ids and URLs come from the Terraform outputs of the environment (needs `terraform` on the PATH).
AWS credentials come from --profile or the environment (locally: AWS_PROFILE, after `aws sso login`).
The identity used needs access to Cognito, SQS and to execute-api:Invoke on the API.
Exit code 0 only if every check passed.
"""

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

DEFAULT_TERRAFORM_DIR = Path(__file__).resolve().parents[1] / "envs" / "dev"

QUEUE_POLL_ROUNDS = 6
QUEUE_WAIT_SECONDS = 5

results = []


def log(message):
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def fail(message):
    print(f"ERROR: {message}", flush=True)
    sys.exit(1)


def check(name, ok, detail=""):
    results.append(ok)
    log(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


# ---------------------------------------------------------------- configuration


def terraform_outputs(directory, profile):
    env = {**os.environ, "AWS_PROFILE": profile} if profile else None
    result = subprocess.run(
        ["terraform", f"-chdir={directory}", "output", "-json"], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        fail(f"terraform output failed in {directory}:\n{result.stderr.strip()}")
    return {name: output["value"] for name, output in json.loads(result.stdout).items()}


# ---------------------------------------------------------------- accounts and tokens


def new_password():
    """Satisfies the policy of the pool: at least 12 characters with lower and upper case, a digit and a symbol."""
    return secrets.token_urlsafe(18) + "aA1!"


def detection_batch(batch_id, device_id):
    """One valid detection as the edge sends it (docs/api/ingest-detections.md); batch_id marks this run."""
    now = datetime.now(timezone.utc)
    frame_id = str(uuid.uuid4())
    return {
        "batchId": batch_id,
        "detections": [{
            "detectionId": str(uuid.uuid4()),
            "frameId": frame_id,
            "detectedAt": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "plate": "SMOKE01",
            "ocrConfidence": 0.9,
            "detectorConfidence": 0.9,
            "imageKey": f"images/{device_id}/{now:%Y/%m/%d}/{frame_id}.jpg",
            "corners": [[0.40, 0.50], [0.45, 0.50], [0.45, 0.55], [0.40, 0.55]],
            "location": {"lat": 52.2297, "lon": 21.0122},
        }],
    }


def claims_of(token):
    """The claims of a JWT. The signature is not checked: the gateway does that, here the claims are only read."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def create_account(cognito, pool_id, username, group):
    password = new_password()
    cognito.admin_create_user(UserPoolId=pool_id, Username=username, MessageAction="SUPPRESS")
    cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=group)
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
    return password


def person_token(cognito, pool_id, client_id, username, password):
    response = cognito.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return response["AuthenticationResult"]["AccessToken"]


def device_token(cognito, client_id, username, password):
    response = cognito.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return response["AuthenticationResult"]["AccessToken"]


# ---------------------------------------------------------------- HTTP


def send(request):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def call(method, url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    return send(urllib.request.Request(url, data=data, headers=headers, method=method))


def signed_call(session, region, method, url, body=None):
    """A request signed with the AWS credentials of the caller (Signature V4), as an administrator sends it."""
    data = None if body is None else json.dumps(body).encode()
    aws_request = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
    SigV4Auth(session.get_credentials().get_frozen_credentials(), "execute-api", region).add_auth(aws_request)
    return send(urllib.request.Request(url, data=data, headers=dict(aws_request.headers), method=method))


def let_in(status):
    """The gateway accepted the caller (whatever the service behind it answered, even 500 or 503 without tasks)."""
    return status not in (401, 403)


def check_status(name, status, ok):
    return check(name, ok, f"status {status}")


# ---------------------------------------------------------------- queue


def find_test_message(sqs, queue_url, marker):
    """The message of this run in the queue, or None. Other messages are released at once, untouched."""
    for _ in range(QUEUE_POLL_ROUNDS):
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=QUEUE_WAIT_SECONDS,
            MessageAttributeNames=["All"],
            VisibilityTimeout=30,
        )
        found = None
        for message in response.get("Messages", []):
            if marker in message["Body"]:
                found = message
            else:
                sqs.change_message_visibility(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0)
        if found:
            return found
    return None


# ---------------------------------------------------------------- the test


def run(session, outputs, region, accounts):
    pool_id = outputs["user_pool_id"]
    web_client = outputs["user_pool_client_ids"]["web"]
    device_client = outputs["user_pool_client_ids"]["device"]
    api = outputs["api_endpoint"].rstrip("/")
    queue_url = outputs["operations_events_queue_url"]
    cognito = session.client("cognito-idp", region_name=region)
    sqs = session.client("sqs", region_name=region)

    suffix = secrets.token_hex(3)
    person, device = f"smoke-user-{suffix}", f"smoke-device-{suffix}"

    log("Creating the test person and the test device")
    accounts.append(person)
    person_password = create_account(cognito, pool_id, person, "users")
    accounts.append(device)
    device_password = create_account(cognito, pool_id, device, "devices")

    person_jwt = person_token(cognito, pool_id, web_client, person, person_password)
    device_jwt = device_token(cognito, device_client, device, device_password)
    person_claims, device_claims = claims_of(person_jwt), claims_of(device_jwt)

    check("person token: account_type = user, issued to the web client",
          person_claims.get("account_type") == "user" and person_claims.get("client_id") == web_client)
    check("device token: account_type = device, issued to the device client",
          device_claims.get("account_type") == "device" and device_claims.get("client_id") == device_client)

    # ingest
    marker = str(uuid.uuid4())  # the batchId, found again in the queue
    batch = detection_batch(marker, device_claims["sub"])
    status, text = call("POST", f"{api}/api/v1/ingest/detections", device_jwt, batch)
    body = json.loads(text) if status == 202 else {}
    check_status("ingest: device token accepted with 202", status, status == 202)
    check("ingest: response names the batch and one accepted detection",
          body.get("batchId") == marker and body.get("accepted") == 1)
    status_invalid, text_invalid = call("POST", f"{api}/api/v1/ingest/detections", device_jwt, {"smokeTest": marker})
    check_status("ingest: invalid batch refused with 400 VALIDATION_FAILED", status_invalid,
                 status_invalid == 400 and json.loads(text_invalid).get("code") == "VALIDATION_FAILED")
    status_person = call("POST", f"{api}/api/v1/ingest/detections", person_jwt, batch)[0]
    check_status("ingest: person token refused with 401", status_person, status_person == 401)
    status_anonymous = call("POST", f"{api}/api/v1/ingest/detections", None, batch)[0]
    check_status("ingest: request without a token refused with 401", status_anonymous, status_anonymous == 401)

    message = find_test_message(sqs, queue_url, marker) if status == 202 else None
    if check("queue: the published event arrived in the operations queue", message is not None):
        attributes = {name: value["StringValue"] for name, value in message["MessageAttributes"].items()}
        check("queue: attributes are eventType = detection, deviceId = sub of the device, no accountId",
              attributes.get("eventType") == "detection"
              and attributes.get("deviceId") == device_claims["sub"]
              and "accountId" not in attributes)
        check("queue: traceId equals the traceId of the response", attributes.get("traceId") == body.get("traceId"))
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])

    # alerts
    status = call("GET", f"{api}/api/v1/alerts")[0]
    check_status("alerts: list without a token refused with 401", status, status == 401)
    status = call("GET", f"{api}/api/v1/alerts", person_jwt)[0]
    check_status("alerts: person may list", status, let_in(status))
    status = call("GET", f"{api}/api/v1/alerts", device_jwt)[0]
    check_status("alerts: device may list", status, let_in(status))
    status = call("POST", f"{api}/api/v1/alerts", person_jwt, {})[0]
    check_status("alerts: person may create", status, let_in(status))
    status = call("POST", f"{api}/api/v1/alerts", device_jwt, {})[0]
    check_status("alerts: device may not create (401)", status, status == 401)

    # device routes of device-management (split by caller)
    status = call("GET", f"{api}/api/v1/device", person_jwt)[0]
    check_status("device: person may read their device", status, let_in(status))
    status = call("GET", f"{api}/api/v1/device/config", device_jwt)[0]
    check_status("device: device may read its configuration", status, let_in(status))
    status = call("PUT", f"{api}/api/v1/device/config", device_jwt, {})[0]
    check_status("device: device may not edit its configuration (401)", status, status == 401)
    status = call("POST", f"{api}/api/v1/device/metrics", person_jwt, {})[0]
    check_status("device: person may not report metrics (401)", status, status == 401)
    status = call("POST", f"{api}/api/v1/images/presigned-urls", device_jwt, {})[0]
    check_status("device: device may ask for upload URLs", status, let_in(status))

    # admin routes (protected by IAM). A random device id: the service answers 404, nothing is deleted.
    admin_url = f"{api}/api/v1/admin/devices/{uuid.uuid4()}"
    status = call("DELETE", admin_url)[0]
    check_status("admin: unsigned request refused with 403", status, status == 403)
    status = call("DELETE", admin_url, person_jwt)[0]
    check_status("admin: person token refused with 403", status, status == 403)
    status = signed_call(session, region, "DELETE", admin_url)[0]
    check_status("admin: signed request let through to the service", status, let_in(status))


def clean_up(session, outputs, region, accounts):
    cognito = session.client("cognito-idp", region_name=region)
    pool_id = outputs["user_pool_id"]
    for username in accounts:
        try:
            cognito.admin_delete_user(UserPoolId=pool_id, Username=username)
            log(f"Deleted test user {username}")
        except cognito.exceptions.UserNotFoundException:
            pass  # it was never created
        except Exception as error:  # keep deleting the others
            check(f"cleanup: deleted {username}", False, f"{type(error).__name__}: {error}")
    left = cognito.list_users(UserPoolId=pool_id, Filter='username ^= "smoke-"')["Users"]
    check("cleanup: no test users left in the pool", not left, f"{len(left)} left")


def main():
    parser = argparse.ArgumentParser(description="Smoke test of the identity model on a deployed environment.")
    parser.add_argument("--profile", default=None, help="AWS profile (default: the environment, e.g. AWS_PROFILE)")
    parser.add_argument("--terraform-dir", default=DEFAULT_TERRAFORM_DIR, help="Terraform root module of the environment")
    args = parser.parse_args()

    outputs = terraform_outputs(args.terraform_dir, args.profile)
    region = outputs["user_pool_id"].split("_")[0]  # eu-central-1_abc123 -> eu-central-1
    session = boto3.Session(profile_name=args.profile, region_name=region)

    accounts = []
    try:
        run(session, outputs, region, accounts)
    except Exception as error:  # report, then still clean up
        check("the test ran to the end", False, f"{type(error).__name__}: {error}")
    finally:
        clean_up(session, outputs, region, accounts)

    log(f"{results.count(True)} of {len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
