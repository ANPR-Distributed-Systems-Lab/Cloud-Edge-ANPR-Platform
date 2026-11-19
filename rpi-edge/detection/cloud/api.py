"""Requests to the platform: the access token, the trace id, one retry after a 401, and whether the platform answers."""
import time
from dataclasses import dataclass

from common.jsonlog import log
from detection.cloud.cognito import AuthError, CognitoAuth
from detection.cloud.transport import Http, NetworkError, Response


@dataclass
class CloudHealth:
    """When the platform last answered and last failed to (monotonic seconds), and whether the device may use it,
    for the LCD and the LEDs in the car (feedback/)."""
    last_answer_at: float | None = None
    last_failure_at: float | None = None
    sign_in_failed: bool = False  # the latest request found no access token (credentials, Cognito)
    forbidden: bool = False  # the latest answer was a 403: the token is not a device token

    @property
    def online(self) -> bool | None:
        """None before the first request; otherwise whether the latest request got an answer."""
        if self.last_answer_at is None and self.last_failure_at is None:
            return None
        return (self.last_answer_at or -1.0) > (self.last_failure_at or -1.0)


class Api:
    def __init__(self, http: Http, auth: CognitoAuth | None, api_base_url: str | None, clock=time.monotonic) -> None:
        self.http = http
        self.auth = auth
        self.api_base_url = api_base_url
        self.clock = clock
        self.health = CloudHealth()

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
        except AuthError:
            self.health.last_failure_at, self.health.sign_in_failed = self.clock(), True
            raise
        self.health.last_answer_at, self.health.sign_in_failed = self.clock(), False
        self.health.forbidden = response.status == 403 and self._authenticated(url)
        return response
