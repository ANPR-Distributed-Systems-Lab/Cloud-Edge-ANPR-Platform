"""Helpers shared by create_device.py and check_platform.py: the environment (Terraform outputs and AWS session),
calls of the platform API and the translation of its error answers into messages for the human.

The low-level calls (HTTP, Signature V4, Terraform outputs) are those of identity_smoke_test.py.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from identity_smoke_test import DEFAULT_TERRAFORM_DIR, call, signed_call, terraform_outputs


class PlatformError(Exception):
    """A failure the human can act on. Its message never contains a password or a token."""


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
