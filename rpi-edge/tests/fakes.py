"""Test doubles: HTTP that answers from a script and records what was sent."""
import hashlib
import json

from detection.cloud.transport import NetworkError, Response


def response(status: int, body=None, headers: dict | None = None) -> Response:
    raw = json.dumps(body).encode() if body is not None else b""
    return Response(status, raw, {k.lower(): v for k, v in (headers or {}).items()})


class FakeHttp:
    """request() returns the queued answers in order (an exception instance is raised instead);
    download() serves the bytes registered per URL."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.requests: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def request(self, method, url, headers=None, body=None):
        self.requests.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def download(self, url, target):
        self.downloads.append(url)
        if url not in self.files:
            raise NetworkError(f"GET {url}: no route")
        target.write_bytes(self.files[url])
        return hashlib.sha256(self.files[url]).hexdigest()


class FakeApi:
    """Api.request() with scripted answers, recording the requests."""

    def __init__(self, *answers) -> None:
        self.http = FakeHttp(*answers)

    @property
    def requests(self):
        return self.http.requests

    def request(self, method, url, trace_id, body=None, headers=None):
        return self.http.request(method, url, headers={"X-Trace-Id": trace_id, **(headers or {})}, body=body)
