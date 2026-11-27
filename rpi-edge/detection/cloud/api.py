"""Requests to the platform: the access token, the trace id, one retry after a 401, whether the platform answers,
and the faults of the device and its account that any answer can show (common/fault_catalog.py):

  no credentials, sign-in refused   Cognito gave no token (cloud/cognito.py)
  401                               token refused: still refused after a renewal (another app client, a wrong pool)
  403 DEVICE_NOT_PAIRED             the device has no owner (operations-service, GET /api/v1/alerts)
  403 otherwise                     not a device token
  404 DEVICE_NOT_FOUND              device-management does not know the device (deleted, or another environment)

Each clears with the next successful answer of the endpoint that showed it. Any other error answer is for the
caller to judge (account_fault() tells whether one of these explains it).
"""
import threading
import time
from dataclasses import dataclass

from common import fault_catalog as kinds
from common.faults import FaultBoard, FaultKind
from common.jsonlog import log
from detection.cloud.cognito import AuthError, CognitoAuth, CredentialsError
from detection.cloud.transport import Http, NetworkError, Response
from detection.contract.problem import Problem


@dataclass
class CloudHealth:
    """When the platform last answered and last failed to (monotonic seconds), and whether the device may use it,
    for the LCD and the LEDs in the car (feedback/)."""
    last_answer_at: float | None = None
    last_failure_at: float | None = None
    sign_in_failed: bool = False  # the latest request got no token: Cognito refused or no credentials
    denied: bool = False  # the latest answer refused the token (401 after a renewal, 403 not a device token)

    @property
    def online(self) -> bool | None:
        """None before the first request; otherwise whether the latest request got an answer."""
        if self.last_answer_at is None and self.last_failure_at is None:
            return None
        return (self.last_answer_at or -1.0) > (self.last_failure_at or -1.0)


def account_fault(response: Response) -> FaultKind | None:
    """The fault of the device or its account an answer shows, if any."""
    if response.status == 401:
        return kinds.TOKEN_REFUSED
    if response.status == 403:
        code = Problem.of(response.status, response.body).code
        return kinds.NO_OWNER if code == "DEVICE_NOT_PAIRED" else kinds.NOT_DEVICE_TOKEN
    if response.status == 404 and Problem.of(response.status, response.body).code == "DEVICE_NOT_FOUND":
        return kinds.DEVICE_NOT_FOUND
    return None


class Api:
    def __init__(self, http: Http, auth: CognitoAuth | None, api_base_url: str | None, faults: FaultBoard,
                 clock=time.monotonic) -> None:
        self.http = http
        self.auth = auth
        self.api_base_url = api_base_url
        self.faults = faults
        self.clock = clock
        self.health = CloudHealth()
        self._shown_by: dict[str, FaultKind] = {}  # endpoint -> the account fault its latest answer showed
        self._lock = threading.Lock()

    def _authenticated(self, url: str) -> bool:
        # The token goes only to the platform, never to a development override such as a mock server.
        return self.auth is not None and self.api_base_url is not None and url.startswith(self.api_base_url + "/")

    def request(self, method: str, url: str, trace_id: str, body=None, headers: dict | None = None) -> Response:
        """Raises NetworkError (no answer) or AuthError (no token); any HTTP status is returned."""
        def send() -> Response:
            all_headers = {"X-Trace-Id": trace_id, **(headers or {})}
            if self._authenticated(url):
                all_headers["Authorization"] = f"Bearer {self.auth.token()}"
            return self.http.request(method, url, headers=all_headers, body=body)

        try:
            response = send()
            if response.status == 401 and self._authenticated(url):
                log("access_token_refused", level="warning", traceId=trace_id)
                self.auth.invalidate()
                response = send()
        except NetworkError:
            self.health.last_failure_at = self.clock()
            raise
        except AuthError as e:
            self.health.last_failure_at, self.health.sign_in_failed = self.clock(), True
            self.faults.report(kinds.NO_CREDENTIALS if isinstance(e, CredentialsError) else kinds.SIGN_IN_REFUSED)
            raise
        self.health.last_answer_at, self.health.sign_in_failed = self.clock(), False
        self.faults.clear(kinds.NO_CREDENTIALS, kinds.SIGN_IN_REFUSED)
        self._account(url, response)
        return response

    def _account(self, url: str, response: Response) -> None:
        """Shows or clears the account fault of this endpoint; a fault another endpoint still shows stays."""
        fault = account_fault(response)
        self.health.denied = fault in (kinds.TOKEN_REFUSED, kinds.NOT_DEVICE_TOKEN)
        endpoint = url.split("?", 1)[0]
        with self._lock:
            before = self._shown_by.pop(endpoint, None)
            if fault is not None:
                self._shown_by[endpoint] = fault
                self.faults.report(fault)
            if before is not None and before is not fault and before not in self._shown_by.values():
                self.faults.clear(before)
