"""Requests to the platform: the access token, the trace id, one retry after a 401, and whether the platform answers."""
import time
from dataclasses import dataclass

from common.jsonlog import log
from detection.cloud.cognito import AuthError, CognitoAuth
from detection.cloud.transport import Http, NetworkError, Response


@dataclass
class CloudHealth:
    """When the platform last answered and last failed to (monotonic seconds), for the screen in the car."""
    last_answer_at: float | None = None
    last_failure_at: float | None = None

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
        except (NetworkError, AuthError):
            self.health.last_failure_at = self.clock()
            raise
        self.health.last_answer_at = self.clock()
        return response
