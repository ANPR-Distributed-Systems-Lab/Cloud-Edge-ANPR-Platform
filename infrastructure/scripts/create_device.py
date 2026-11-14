"""Pair an edge device with the account of a person, or delete a device again (docs/device-management.md, section 5).

    python create_device.py --person-username <username> --out <file> [--device-username rpi-01] [--force]
    python create_device.py --account-id <sub> --out <file>
    python create_device.py --delete <deviceId>

Calls POST /api/v1/admin/devices (DELETE /api/v1/admin/devices/{deviceId}), signed with the AWS credentials of
--profile (Signature V4): the IAM principal needs execute-api:Invoke on the admin routes. The person is given as
account id (the Cognito sub) or as username, which is looked up in the user pool.

The password of the device is generated here (random, it meets the policy of the user pool), sent to the service
and written, with the username, to --out as {"username": "...", "password": "..."}. It is never printed. Secrets
do not belong in the repository, so --out inside it is refused, and so is overwriting a file without --force.
Copy the file to the config volume of the Pi and delete it (the steps are printed).

The ids and URLs come from the Terraform outputs of the environment (needs `terraform` on the PATH). AWS credentials
come from --profile or the environment (locally: AWS_PROFILE, after `aws sso login`).
"""

import argparse
import json
import os
import re
import secrets
import string
import uuid
from dataclasses import dataclass
from pathlib import Path

from api_client import PlatformError, add_environment_arguments, expect, open_environment, run_cli, signed_request

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEVICE_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")  # CreateDeviceRequest.username
DEFAULT_DEVICE_USERNAME = "rpi-01"

# Policy of the user pool (modules/cognito-user-pool): at least 12 characters, lower and upper case, a digit, a symbol.
PASSWORD_LENGTH = 24
PASSWORD_CLASSES = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!#%*+-=?_")

ADMIN_FORBIDDEN = (
    "The gateway refused the signature. Use an AWS profile whose principal may execute-api:Invoke on the admin "
    "routes, and log in again (aws sso login) if the session has expired."
)
CREATE_MESSAGES = {
    400: "The API rejected the request. A password field means the generated password broke the policy of the pool.",
    403: ADMIN_FORBIDDEN,
    404: "The account does not exist or is not a person (a user of the group users).",
    "USERNAME_TAKEN": "A device with this username already exists: pass another --device-username.",
    "ACCOUNT_HAS_DEVICE": "The account already has a device: delete it first with --delete <deviceId>.",
}
DELETE_MESSAGES = {
    400: "The device id is malformed.",
    403: ADMIN_FORBIDDEN,
    404: "No such device (already deleted?).",
}


@dataclass(frozen=True)
class CreatedDevice:
    device_id: str
    account_id: str
    username: str

    @classmethod
    def parse(cls, body):
        return cls(body["deviceId"], body["accountId"], body["username"])


# ---------------------------------------------------------------- password and credentials file


def generate_password(length=PASSWORD_LENGTH):
    """Random, with at least one character of every class of the policy; shuffled so the classes have no fixed place."""
    characters = [secrets.choice(chars) for chars in PASSWORD_CLASSES]
    alphabet = "".join(PASSWORD_CLASSES)
    characters += [secrets.choice(alphabet) for _ in range(length - len(characters))]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def is_inside(path, directory):
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(directory)]) == os.path.normcase(directory)
    except ValueError:  # another drive
        return False


def ensure_can_write(out, force):
    """Checked before anything is created, so a refusal leaves no device behind."""
    path = out.resolve()
    if is_inside(path, REPOSITORY_ROOT):
        raise PlatformError(f"Refusing to write secrets inside the repository ({REPOSITORY_ROOT}): choose a path outside it.")
    if path.is_dir():
        raise PlatformError(f"{path} is a directory: --out is the path of the file.")
    if path.exists() and not force:
        raise PlatformError(f"{path} already exists: use --force to overwrite it.")
    if not path.parent.is_dir():
        raise PlatformError(f"The directory {path.parent} does not exist.")
    return path


def write_credentials(path, username, password, force):
    """UTF-8 without BOM, readable by the owner only (where the OS supports modes). Without --force never overwrites."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8", newline="\n") as file:
        json.dump({"username": username, "password": password}, file)
        file.write("\n")
    os.chmod(path, 0o600)  # also when the file existed before


# ---------------------------------------------------------------- the API


def resolve_account_id(cognito, pool_id, username):
    """The sub of a person, found by username."""
    try:
        user = cognito.admin_get_user(UserPoolId=pool_id, Username=username)
    except cognito.exceptions.UserNotFoundException:
        raise PlatformError(f"No user {username} in the user pool.")
    return next(attribute["Value"] for attribute in user["UserAttributes"] if attribute["Name"] == "sub")


def create_device(environment, account_id, username, password):
    body = {"accountId": account_id, "username": username, "password": password}
    response = signed_request(environment, "POST", f"{environment.api}/api/v1/admin/devices", body)
    return CreatedDevice.parse(expect(response, 201, CREATE_MESSAGES).json())


def delete_device(environment, device_id):
    response = signed_request(environment, "DELETE", f"{environment.api}/api/v1/admin/devices/{device_id}")
    expect(response, 204, DELETE_MESSAGES)


def pair_device(environment, account_id, username, out, force):
    """Creates the device and writes its credentials; if the file cannot be written, the device is removed again."""
    password = generate_password()
    device = create_device(environment, account_id, username, password)
    try:
        write_credentials(out, device.username, password, force)
    except OSError as error:
        try:
            delete_device(environment, device.device_id)
            outcome = "The device was deleted again, so the command can be repeated."
        except PlatformError:
            outcome = f"The device still exists: delete it with --delete {device.device_id}."
        raise PlatformError(f"Could not write {out} ({type(error).__name__}). {outcome}")
    return device


# ---------------------------------------------------------------- command line


def device_username(value):
    if not DEVICE_USERNAME_PATTERN.match(value):
        raise argparse.ArgumentTypeError("lowercase letters, digits and hyphens, 3 to 63 characters, not starting with a hyphen")
    return value


def uuid_text(value):
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("not a UUID")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Pair an edge device with a person, or delete a device.")
    person = parser.add_mutually_exclusive_group()
    person.add_argument("--account-id", type=uuid_text, help="Account id (Cognito sub) of the person who becomes the owner")
    person.add_argument("--person-username", help="Username of the person (looked up in the user pool)")
    parser.add_argument("--device-username", type=device_username, default=DEFAULT_DEVICE_USERNAME,
                        help="Login of the device (default: %(default)s)")
    parser.add_argument("--out", type=Path, help="Where to write the credentials file (outside the repository)")
    parser.add_argument("--force", action="store_true", help="Overwrite --out if it exists")
    parser.add_argument("--delete", type=uuid_text, metavar="DEVICE_ID", help="Delete this device instead of creating one")
    add_environment_arguments(parser)
    args = parser.parse_args(argv)

    if args.delete and (args.account_id or args.person_username or args.out):
        parser.error("--delete cannot be combined with --account-id, --person-username or --out")
    if not args.delete and not ((args.account_id or args.person_username) and args.out):
        parser.error("give the person (--account-id or --person-username) and --out, or --delete DEVICE_ID")
    return args


def run(args):
    if args.delete:
        delete_device(open_environment(args.profile, args.terraform_dir), args.delete)
        print(f"Deleted device {args.delete}.")
        return

    out = ensure_can_write(args.out, args.force)
    environment = open_environment(args.profile, args.terraform_dir)
    account_id = args.account_id or resolve_account_id(
        environment.session.client("cognito-idp"), environment.pool_id, args.person_username)
    device = pair_device(environment, account_id, args.device_username, out, args.force)

    print("Created the device:")
    print(f"  deviceId:  {device.device_id}")
    print(f"  accountId: {device.account_id}")
    print(f"  username:  {device.username}")
    print(f"Credentials written to {out}\n")
    print("Next steps:")
    print(f"  1. docker compose cp {out} rpi-edge:/config/device-credentials.json")
    print("  2. Delete the local file.")
    print(f"A failed test is cleaned up with: python create_device.py --delete {device.device_id}")


def main(argv=None):
    args = parse_args(argv)
    run_cli(lambda: run(args))


if __name__ == "__main__":
    main()
