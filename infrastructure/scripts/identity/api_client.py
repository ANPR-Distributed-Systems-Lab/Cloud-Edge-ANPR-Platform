"""Helpers shared by the scripts that talk to a deployed environment (create_device.py and check_platform.py): the
environment (Terraform outputs and AWS session), the HTTP calls of the platform API and the translation of its error
answers into messages for the human.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_TERRAFORM_DIR = Path(__file__).resolve().parents[2] / "envs" / "dev"


class PlatformError(Exception):
    """A failure the human can act on. Its message never contains a password or a token."""


# ---------------------------------------------------------------- Terraform and HTTP


def terraform_outputs(directory, profile):
    env = {**os.environ, "AWS_PROFILE": profile} if profile else None
    result = subprocess.run(
        ["terraform", f"-chdir={directory}", "output", "-json"], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise PlatformError(f"terraform output failed in {directory}:\n{result.stderr.strip()}")
    return {name: output["value"] for name, output in json.loads(result.stdout).items()}


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


# ---------------------------------------------------------------- the environment


@dataclass(frozen=True)
class Environment:
    api: str
    region: str
    pool_id: str
    web_client_id: str
    session: boto3.Session


def add_environment_arguments(parser):
    parser.add_argument("--profile", default=None, help="AWS profile (default: the environment, e.g. AWS_PROFILE)")
    parser.add_argument("--terraform-dir", default=DEFAULT_TERRAFORM_DIR, help="Terraform root module of the environment")


def open_environment(profile, terraform_dir):
    """Reads the Terraform outputs (a failure there ends the script with its message) and opens the AWS session."""
    outputs = terraform_outputs(terraform_dir, profile)
    pool_id = outputs["user_pool_id"]
    region = pool_id.split("_")[0]  # eu-central-1_abc123 -> eu-central-1
    return Environment(
        api=outputs["api_endpoint"].rstrip("/"),
        region=region,
        pool_id=pool_id,
        web_client_id=outputs["user_pool_client_ids"]["web"],
        session=boto3.Session(profile_name=profile, region_name=region),
    )


# ---------------------------------------------------------------- answers of the API


@dataclass(frozen=True)
class Problem:
    """The parts of an RFC 9457 error body that are safe to print: never the free-text detail."""
    code: str | None
    fields: tuple[str, ...]  # "field CODE"
    request_id: str | None


@dataclass(frozen=True)
class ApiResponse:
    status: int
    text: str

    def json(self):
        return json.loads(self.text)

    def problem(self):
        """The error body, or an empty Problem when the answer is not one (the gateway answers 401 and 403 itself)."""
        try:
            body = self.json()
            fields = tuple(f"{item['field']} {item['code']}" for item in body.get("fields", []))
            return Problem(body.get("code"), fields, body.get("requestId"))
        except (ValueError, AttributeError, KeyError, TypeError):
            return Problem(None, (), None)


def failure(response, messages):
    """The error for an unexpected answer. `messages` maps an error code or a status to the text for the human."""
    problem = response.problem()
    text = messages.get(problem.code) or messages.get(response.status) or f"The API answered {response.status}."
    if problem.fields:
        text += f" Fields: {', '.join(problem.fields)}."
    if problem.request_id:
        text += f" (request {problem.request_id})"
    return PlatformError(text)


def expect(response, status, messages):
    if response.status != status:
        raise failure(response, messages)
    return response


def bearer_request(method, url, token, body=None):
    return ApiResponse(*call(method, url, token, body))


def signed_request(environment, method, url, body=None):
    """A request signed by the IAM principal of the AWS profile (what the admin routes require)."""
    if environment.session.get_credentials() is None:
        raise PlatformError("No AWS credentials: pass --profile or set AWS_PROFILE (after `aws sso login`).")
    return ApiResponse(*signed_call(environment.session, environment.region, method, url, body))


def run_cli(action):
    """Runs the action; a failure becomes one message on stderr and exit code 1 instead of a traceback."""
    try:
        action()
    except PlatformError as error:
        message = str(error)
    except ClientError as error:
        message = f"AWS refused the call: {error.response['Error']['Code']}: {error.response['Error']['Message']}"
    except BotoCoreError as error:  # e.g. an expired SSO session
        message = f"AWS access failed: {type(error).__name__}: {error}"
    except OSError as error:  # network, file
        message = f"{type(error).__name__}: {error}"
    else:
        return
    print(message, file=sys.stderr)
    sys.exit(1)
