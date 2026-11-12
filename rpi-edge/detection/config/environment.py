"""Where the platform is: rpi-edge/.env, passed in by docker compose, fixed for the life of the container."""
import os
from dataclasses import dataclass
from pathlib import Path

INGEST_PATH = "/api/v1/ingest/detections"
MODELS_PATH = "/api/v1/device/models"
CONFIG_PATH = "/api/v1/device/config"


@dataclass(frozen=True)
class Environment:
    api_base_url: str | None  # API Gateway, e.g. https://abc123.execute-api.eu-central-1.amazonaws.com
    cognito_region: str | None
    cognito_client_id: str | None  # the public `device` app client
    ingest_url: str | None
    models_manifest_url: str | None
    config_url: str | None  # None: no polling of the cloud configuration
    config_dir: Path
    state_dir: Path
    replay_dir: Path | None = None  # recorded frames instead of the camera (vision/replay.py)

    @property
    def credentials_file(self) -> Path:
        """Username and password of the device account, placed on the device at pairing (DETECTION.md)."""
        return self.config_dir / "device-credentials.json"

    @property
    def signs_in(self) -> bool:
        return bool(self.cognito_region and self.cognito_client_id)

    @classmethod
    def from_env(cls, env=os.environ) -> "Environment":
        api = (env.get("API_BASE_URL") or "").rstrip("/") or None

        def endpoint(override: str, path: str) -> str | None:
            # A development override (mock server) wins over the endpoint of the platform.
            return env.get(override) or (api + path if api else None)

        return cls(
            api_base_url=api,
            cognito_region=env.get("COGNITO_REGION") or None,
            cognito_client_id=env.get("COGNITO_CLIENT_ID") or None,
            ingest_url=endpoint("INGEST_URL", INGEST_PATH),
            models_manifest_url=endpoint("MODELS_MANIFEST_URL", MODELS_PATH),
            config_url=api + CONFIG_PATH if api else None,
            config_dir=Path(env.get("CONFIG_DIR", "/config")),
            state_dir=Path(env.get("STATE_DIR", "/state")),
            replay_dir=Path(env["REPLAY_DIR"]) if env.get("REPLAY_DIR") else None,
        )
