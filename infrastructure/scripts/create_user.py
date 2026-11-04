"""Create the account of a person (group "users") in the user pool of an environment (docs/identity-and-access.md).

    python create_user.py <username> [--profile dev] [--terraform-dir infrastructure/envs/dev]

The password is asked for twice and never echoed; it is not a command-line option, so it does not stay in the shell
history. It must meet the password policy of the pool: at least 12 characters with lower and upper case, a digit and
a symbol. The account is created with a permanent password and without any message (the pool has no e-mail).

Prints the account id (Cognito sub): an administrator passes it as accountId when creating a device for the person
(POST /api/v1/admin/devices). If a step fails after the user was created, the half-created user is deleted again.

The pool id comes from the Terraform outputs of the environment (needs `terraform` on the PATH). AWS credentials
come from --profile or the environment (locally: AWS_PROFILE, after `aws sso login`).
"""

import argparse
import getpass
import json
import os
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

# The group of people, as in local.account_type_by_group (infrastructure/envs/dev/auth.tf).
USERS_GROUP = "users"
DEFAULT_TERRAFORM_DIR = os.path.join(os.path.dirname(__file__), "..", "envs", "dev")


class AccountError(Exception):
    """A refusal of the user pool that the administrator can act on (taken username, weak password)."""


def create_person(cognito, pool_id, username, password):
    """Creates the user with a permanent password in the group of people and returns its sub (the account id)."""
    try:
        user = cognito.admin_create_user(UserPoolId=pool_id, Username=username, MessageAction="SUPPRESS")["User"]
    except cognito.exceptions.UsernameExistsException:
        raise AccountError(f"The username {username} is already taken")

    try:
        cognito.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
        cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=USERS_GROUP)
    except ClientError as error:
        cognito.admin_delete_user(UserPoolId=pool_id, Username=username)
        if error.response["Error"]["Code"] == "InvalidPasswordException":
            raise AccountError(f"The password does not meet the policy of the pool: {error.response['Error']['Message']}")
        raise
    return next(attribute["Value"] for attribute in user["Attributes"] if attribute["Name"] == "sub")


def read_password(prompt=getpass.getpass):
    password = prompt("Password: ")
    if password != prompt("Repeat the password: "):
        raise AccountError("The passwords do not match")
    return password


def user_pool_id(terraform_dir, profile):
    env = {**os.environ, "AWS_PROFILE": profile} if profile else None
    result = subprocess.run(
        ["terraform", f"-chdir={terraform_dir}", "output", "-json", "user_pool_id"], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise AccountError(f"terraform output failed in {terraform_dir}:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Create the account of a person in the user pool.")
    parser.add_argument("username")
    parser.add_argument("--profile", default=None, help="AWS profile (default: the environment, e.g. AWS_PROFILE)")
    parser.add_argument("--terraform-dir", default=DEFAULT_TERRAFORM_DIR, help="Terraform root module of the environment")
    args = parser.parse_args()

    try:
        pool_id = user_pool_id(args.terraform_dir, args.profile)
        region = pool_id.split("_")[0]  # eu-central-1_abc123 -> eu-central-1
        cognito = boto3.Session(profile_name=args.profile, region_name=region).client("cognito-idp")
        account_id = create_person(cognito, pool_id, args.username, read_password())
    except AccountError as error:
        print(error, file=sys.stderr)
        sys.exit(1)

    print(f"Created {args.username}, account id: {account_id}")


if __name__ == "__main__":
    main()
