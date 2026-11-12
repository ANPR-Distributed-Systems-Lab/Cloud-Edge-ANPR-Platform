"""The only module that touches the network. Tests replace Http with a fake that has the same two methods."""
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import requests

TIMEOUT_SECONDS = 15


class NetworkError(Exception):
    """No answer: no connection, DNS failure, timeout. The caller retries later."""


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)  # lower-case names

    def json(self):
        return json.loads(self.body) if self.body else None


class Http:
    def __init__(self) -> None:
        self.session = requests.Session()

    def request(self, method: str, url: str, headers: dict | None = None, body=None) -> Response:
        """body is sent as JSON when given."""
        try:
            r = self.session.request(method, url, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise NetworkError(f"{method} {_without_query(url)}: {type(e).__name__}") from None
        return Response(r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()})

    def download(self, url: str, target: Path) -> str:
        """Streams url into target and returns its SHA-256. No headers: presigned URLs carry their own signature."""
        digest = hashlib.sha256()
        try:
            with self.session.get(url, stream=True, timeout=TIMEOUT_SECONDS) as r:
                if r.status_code != 200:
                    raise NetworkError(f"GET {_without_query(url)}: HTTP {r.status_code}")
                with open(target, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        digest.update(chunk)
                    f.flush()
                    os.fsync(f.fileno())
        except requests.RequestException as e:
            raise NetworkError(f"GET {_without_query(url)}: {type(e).__name__}") from None
        return digest.hexdigest()


def _without_query(url: str) -> str:
    """Presigned URLs carry credentials in the query string: never log it."""
    return url.split("?", 1)[0]
