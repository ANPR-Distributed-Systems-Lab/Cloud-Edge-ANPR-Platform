"""Sign-in of the device account with Amazon Cognito (docs/identity-and-access.md, section 3).

The `device` app client is public (no secret) and allows USER_PASSWORD_AUTH and REFRESH_TOKEN_AUTH. The
device signs in with its username and password once, then renews the access token with the refresh token,
and falls back to the password when the refresh token is refused (expired, revoked). Tokens stay in memory.
"""
import json
import time
from pathlib import Path

from common.jsonlog import log
from detection.cloud.transport import Http, NetworkError

RENEW_BEFORE_SECONDS = 120  # renew a little before expiry, so a request never leaves with a dying token


class AuthError(Exception):
    """No access token could be obtained (wrong credentials, missing file, Cognito unreachable)."""


class CognitoAuth:
    def __init__(self, region: str, client_id: str, credentials_file: Path, http: Http, clock=time.monotonic):
        self.url = f"https://cognito-idp.{region}.amazonaws.com/"
        self.client_id = client_id
        self.credentials_file = credentials_file
        self.http = http
        self.clock = clock
        self._access: str | None = None
        self._expires_at = 0.0
        self._refresh: str | None = None

    def token(self) -> str:
        """A valid access token, renewed or obtained when needed."""
        if self._access is None or self.clock() >= self._expires_at - RENEW_BEFORE_SECONDS:
            self._renew()
        return self._access

    def invalidate(self) -> None:
        """Called after a 401: the next token() renews even if the token looks valid."""
        self._access = None

    def _renew(self) -> None:
        if self._refresh is not None:
            try:
                self._store(self._initiate("REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": self._refresh}))
                return
            except AuthError as e:
                log("cognito_refresh_failed", level="warning", error=str(e))
                self._refresh = None
        username, password = self._credentials()
        self._store(self._initiate("USER_PASSWORD_AUTH", {"USERNAME": username, "PASSWORD": password}))
        log("cognito_signed_in", username=username)

    def _initiate(self, flow: str, parameters: dict) -> dict:
        headers = {"Content-Type": "application/x-amz-json-1.1",
                   "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"}
        body = {"AuthFlow": flow, "ClientId": self.client_id, "AuthParameters": parameters}
        try:
            response = self.http.request("POST", self.url, headers=headers, body=body)
        except NetworkError as e:
            raise AuthError(str(e)) from None
        payload = response.json() or {}
        if response.status != 200 or "AuthenticationResult" not in payload:
            # Cognito errors are {"__type": "NotAuthorizedException", "message": ...}; neither holds a secret.
            raise AuthError(f"{flow}: HTTP {response.status} {payload.get('__type', '')}".strip())
        return payload["AuthenticationResult"]

    def _store(self, result: dict) -> None:
        self._access = result["AccessToken"]
        self._expires_at = self.clock() + int(result.get("ExpiresIn", 3600))
        self._refresh = result.get("RefreshToken", self._refresh)  # present on sign-in, or with token rotation

    def _credentials(self) -> tuple[str, str]:
        try:
            with open(self.credentials_file, encoding="utf-8") as f:
                data = json.load(f)
            return data["username"], data["password"]
        except (OSError, ValueError, KeyError) as e:
            raise AuthError(f"device credentials unusable ({self.credentials_file}): {type(e).__name__}") from None
