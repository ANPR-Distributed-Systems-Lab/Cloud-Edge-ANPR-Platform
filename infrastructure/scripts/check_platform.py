"""Look at the result of a test as the owner of a device: sign in as a person and read what the platform shows them.

    python check_platform.py --username <person> device
    python check_platform.py --username <person> detections [--limit 10] [--show-plates]
    python check_platform.py --username <person> alert PLATE [--text "..."]
    python check_platform.py --username <person> alert --list [--show-plates]

  device       the device of the person: online state, last metrics, its configuration (version, models and
               thresholds of the send rule) and the latest measurements
  detections   the latest detections of the account (searchDetections)
  alert        creates an alert for a plate, or lists the alerts of the account

The person signs in with USER_PASSWORD_AUTH on the web app client. The password is read from the environment
variable CHECK_PLATFORM_PASSWORD, otherwise asked for without echo; it is not an option, so it stays out of the shell
history. Neither the password nor the tokens are printed. Plate numbers are personal data: they are masked (the first
two characters and the length) unless --show-plates is given.

The web client of the dev environment allows no USER_PASSWORD_AUTH (infrastructure/envs/dev/auth.tf), so the sign-in
is refused with a message saying so. --admin-auth signs in with ADMIN_USER_PASSWORD_AUTH instead, which the web
client allows for testing; it needs the AWS credentials of --profile with cognito-idp:AdminInitiateAuth.

The ids and URLs come from the Terraform outputs of the environment (needs `terraform` on the PATH).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from botocore.exceptions import ClientError

from api_client import PlatformError, add_environment_arguments, bearer_request, expect, open_environment, run_cli

PASSWORD_VARIABLE = "CHECK_PLATFORM_PASSWORD"
PLATE_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")  # Plate in operations-api.yaml
LATEST_METRICS = 3
ALERT_PAGE_SIZE = 100  # the most the API gives; the account of a test has a few alerts

AUTHORIZATION_MESSAGES = {
    401: "The gateway refused the token (401): the account must be a person (group users) signed in on the web client.",
}
DEVICE_MESSAGES = {**AUTHORIZATION_MESSAGES, 404: "No device is paired with this account."}
CREATE_ALERT_MESSAGES = {
    **AUTHORIZATION_MESSAGES,
    400: "The API rejected the alert.",
    "ALERT_ALREADY_EXISTS": "The account already has an alert for this plate.",
}
READ_MESSAGES = {**AUTHORIZATION_MESSAGES, 400: "The API rejected the request."}


# ---------------------------------------------------------------- parsed answers (only what is printed)


@dataclass(frozen=True)
class Device:
    device_id: str
    username: str
    online: bool
    last_metrics_at: str | None

    @classmethod
    def parse(cls, body):
        return cls(body["deviceId"], body["username"], body["online"], body.get("lastMetricsAt"))


@dataclass(frozen=True)
class Configuration:
    version: int
    detector: str
    ocr: str
    plate_cooldown_seconds: int
    ml: dict  # the thresholds of the send rule, printed as they come

    @classmethod
    def parse(cls, body):
        return cls(body["version"], body["models"]["detector"], body["models"]["ocr"],
                   body["plateCooldownSeconds"], body["ml"])


@dataclass(frozen=True)
class Metric:
    recorded_at: str
    cpu_temperature_c: float
    processing_fps: float
    detections_pending: int
    locations_pending: int
    images_pending: int
    gps_fix: str
    satellites: int

    @classmethod
    def parse(cls, body):
        queues, gps = body["queues"], body["gps"]
        return cls(body["recordedAt"], body["cpuTemperatureC"], body["processingFps"], queues["detectionsPending"],
                   queues["locationsPending"], queues["imagesPending"], gps["fix"], gps["satellites"])


@dataclass(frozen=True)
class Detection:
    detection_id: str
    detected_at: str
    plate: str
    ocr_confidence: float
    detector_confidence: float
    has_position: bool
    has_image: bool

    @classmethod
    def parse(cls, body):
        return cls(body["detectionId"], body["detectedAt"], body["plate"], body["ocrConfidence"],
                   body["detectorConfidence"], body.get("position") is not None, bool(body.get("imageUrl")))


@dataclass(frozen=True)
class Alert:
    alert_id: str
    plate: str
    created_at: str
    last_detected_at: str | None

    @classmethod
    def parse(cls, body):
        return cls(body["alertId"], body["plate"], body["createdAt"], body.get("lastDetectedAt"))


# ---------------------------------------------------------------- sign-in


def read_password(prompt=getpass.getpass):
    return os.environ.get(PASSWORD_VARIABLE) or prompt("Password: ")


def sign_in(environment, username, password, admin_auth=False):
    """The access token of the person. Cognito's own refusals are turned into messages; nothing secret is printed."""
    cognito = environment.session.client("cognito-idp")
    credentials = {"USERNAME": username, "PASSWORD": password}
    try:
        if admin_auth:
            response = cognito.admin_initiate_auth(UserPoolId=environment.pool_id, ClientId=environment.web_client_id,
                                                   AuthFlow="ADMIN_USER_PASSWORD_AUTH", AuthParameters=credentials)
        else:
            response = cognito.initiate_auth(ClientId=environment.web_client_id, AuthFlow="USER_PASSWORD_AUTH",
                                             AuthParameters=credentials)
    except ClientError as error:
        raise refusal(error.response["Error"]) from None

    token = response.get("AuthenticationResult", {}).get("AccessToken")
    if token is None:
        raise PlatformError(f"Sign-in needs a further step ({response.get('ChallengeName')}) that this script does not handle.")
    return token


def refusal(error):
    code, message = error["Code"], error["Message"]
    if code == "InvalidParameterException" and "not enabled" in message:
        return PlatformError(
            "The web app client does not allow USER_PASSWORD_AUTH (explicit_auth_flows in infrastructure/envs/dev/auth.tf "
            "lists only SRP, ADMIN_USER_PASSWORD_AUTH and refresh). Add ALLOW_USER_PASSWORD_AUTH to the web client, or "
            "pass --admin-auth to sign in with ADMIN_USER_PASSWORD_AUTH.")
    if code == "NotAuthorizedException":
        return PlatformError("Sign-in refused: wrong username or password (or the user is disabled).")
    return PlatformError(f"Sign-in failed: {code}: {message}")


# ---------------------------------------------------------------- the API as the person


@dataclass(frozen=True)
class PlatformApi:
    base_url: str
    token: str

    def get(self, path, params=None, messages=READ_MESSAGES):
        query = f"?{urlencode(params)}" if params else ""
        return expect(bearer_request("GET", f"{self.base_url}{path}{query}", self.token), 200, messages).json()

    def create(self, path, body, messages):
        return expect(bearer_request("POST", f"{self.base_url}{path}", self.token, body), 201, messages).json()


def mask_plate(plate):
    """The first two characters and the length: WA1234X -> WA*****."""
    return plate[:2] + "*" * (len(plate) - 2) if len(plate) > 2 else "*" * len(plate)


def show_plate(plate, show_plates):
    return plate if show_plates else mask_plate(plate)


# ---------------------------------------------------------------- commands: each returns the lines to print


def device_report(api, args):
    device = Device.parse(api.get("/api/v1/device", messages=DEVICE_MESSAGES))
    configuration = Configuration.parse(api.get("/api/v1/device/config", messages=DEVICE_MESSAGES))
    measurements = api.get("/api/v1/device/metrics", {"limit": LATEST_METRICS}, DEVICE_MESSAGES)["metrics"]

    lines = [
        f"deviceId:        {device.device_id}",
        f"username:        {device.username}",
        f"online:          {device.online}",
        f"lastMetricsAt:   {device.last_metrics_at}",
        f"configuration:   version {configuration.version}",
        f"  models:        detector {configuration.detector}, ocr {configuration.ocr}",
        f"  plateCooldownSeconds: {configuration.plate_cooldown_seconds}",
    ]
    lines += [f"  {name}: {value}" for name, value in configuration.ml.items()]
    lines.append(f"latest metrics ({len(measurements)}), newest first:")
    lines += [metric_line(Metric.parse(item)) for item in reversed(measurements)]
    return lines


def metric_line(metric):
    return (f"  {metric.recorded_at}  cpu {metric.cpu_temperature_c} C  fps {metric.processing_fps}"
            f"  queues d/l/i {metric.detections_pending}/{metric.locations_pending}/{metric.images_pending}"
            f"  gps {metric.gps_fix} ({metric.satellites} satellites)")


def detections_report(api, args):
    page = api.get("/api/v1/detections/search", {"size": args.limit, "sort": "DETECTED_AT", "direction": "DESC"})
    detections = [Detection.parse(item) for item in page["items"]]
    lines = [f"{len(detections)} detections shown, {page['page']['totalElements']} in total (newest first)"]
    lines += [detection_line(detection, args.show_plates) for detection in detections]
    return lines


def detection_line(detection, show_plates):
    return (f"  {detection.detection_id}  {detection.detected_at}  plate {show_plate(detection.plate, show_plates)}"
            f"  ocr {detection.ocr_confidence}  detector {detection.detector_confidence}"
            f"  coordinates {yes_no(detection.has_position)}  image {yes_no(detection.has_image)}")


def yes_no(value):
    return "yes" if value else "no"


def alert_report(api, args):
    if args.list:
        return alert_list(api, args.show_plates)
    alert = api.create("/api/v1/alerts", alert_request(args.plate, args.text), CREATE_ALERT_MESSAGES)
    return [f"Created alert {alert['alertId']} for {show_plate(args.plate, args.show_plates)}"]


def alert_request(plate, text):
    return {"plate": plate} if text is None else {"plate": plate, "alertText": text}


def alert_list(api, show_plates):
    page = api.get("/api/v1/alerts", {"size": ALERT_PAGE_SIZE})
    alerts = [Alert.parse(item) for item in page["items"]]
    lines = [f"{len(alerts)} alerts shown, {page['page']['totalElements']} in total"]
    lines += [f"  {alert.alert_id}  plate {show_plate(alert.plate, show_plates)}  created {alert.created_at}"
              f"  last detected {alert.last_detected_at}" for alert in alerts]
    return lines


# ---------------------------------------------------------------- command line


def plate_text(value):
    if not PLATE_PATTERN.match(value):
        raise argparse.ArgumentTypeError("uppercase letters and digits only, 2 to 10 characters")
    return value


def positive_limit(value):
    if not 1 <= int(value) <= 1000:
        raise argparse.ArgumentTypeError("between 1 and 1000")
    return int(value)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Look at the platform as the owner of a device.")
    parser.add_argument("--username", required=True, help="Username of the person")
    parser.add_argument("--admin-auth", action="store_true",
                        help="Sign in with ADMIN_USER_PASSWORD_AUTH (AWS credentials needed) instead of USER_PASSWORD_AUTH")
    add_environment_arguments(parser)
    plates = argparse.ArgumentParser(add_help=False)
    plates.add_argument("--show-plates", action="store_true", help="Print plate numbers in full instead of masked")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("device", help="The device, its configuration and latest metrics").set_defaults(report=device_report)

    detections = commands.add_parser("detections", parents=[plates], help="The latest detections of the account")
    detections.add_argument("--limit", type=positive_limit, default=10, help="How many (default: %(default)s)")
    detections.set_defaults(report=detections_report)

    alert = commands.add_parser("alert", parents=[plates], help="Create an alert for a plate, or list the alerts")
    alert.add_argument("plate", nargs="?", type=plate_text, help="Plate to watch for")
    alert.add_argument("--text", help="Alert text")
    alert.add_argument("--list", action="store_true", help="List the alerts of the account instead")
    alert.set_defaults(report=alert_report)

    args = parser.parse_args(argv)
    if args.command == "alert" and args.list == (args.plate is not None):
        parser.error("alert: give a PLATE, or --list")
    return args


def run(args):
    password = read_password()
    environment = open_environment(args.profile, args.terraform_dir)
    api = PlatformApi(environment.api, sign_in(environment, args.username, password, args.admin_auth))
    print("\n".join(args.report(api, args)))


def main(argv=None):
    args = parse_args(argv)
    run_cli(lambda: run(args))


if __name__ == "__main__":
    main()
