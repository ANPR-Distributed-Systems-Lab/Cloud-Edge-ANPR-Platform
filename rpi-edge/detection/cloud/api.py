"""Requests to the platform: the access token, the trace id, one retry after a 401."""
from common.jsonlog import log
from detection.cloud.cognito import CognitoAuth
from detection.cloud.transport import Http, Response


class Api:
    def __init__(self, http: Http, auth: CognitoAuth | None, api_base_url: str | None) -> None:
        self.http = http
        self.auth = auth
        self.api_base_url = api_base_url

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

        response = send()
        if response.status == 401 and self._authenticated(url):
            log("access_token_refused", level="warning", traceId=trace_id)
            self.auth.invalidate()
            response = send()
        return response
