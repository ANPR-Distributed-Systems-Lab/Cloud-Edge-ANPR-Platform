"""Where the platform is: rpi-edge/.env, passed in by docker compose, fixed for the life of the container."""
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = "/api/v1/device/config"
MODELS_PATH = "/api/v1/device/models"
INGEST_PATH = "/api/v1/ingest/detections"
ALERTS_PATH = "/api/v1/alerts"


class EnvironmentIncomplete(ValueError):
    pass


@dataclass(frozen=True)
class Environment:
    api_base_url: str  # API Gateway (https://...execute-api...), or tools/dev_cloud.py during development
    cognito_region: str | None
    cognito_client_id: str | None  # the public `device` app client; without it requests carry no token
    config_dir: Path
    state_dir: Path
    replay_dir: Path | None = None  # recorded frames instead of the camera (vision/replay.py)

    @property
    def config_url(self) -> str:
        return self.api_base_url + CONFIG_PATH

    @property
    def models_url(self) -> str:
        return self.api_base_url + MODELS_PATH

    @property
    def ingest_url(self) -> str:
        return self.api_base_url + INGEST_PATH

    @property
    def alerts_url(self) -> str:
        return self.api_base_url + ALERTS_PATH

    @property
    def credentials_file(self) -> Path:
        """Username and password of the device account, placed on the device at pairing (DETECTION.md)."""
        return self.config_dir / "device-credentials.json"

    @property
    def signs_in(self) -> bool:
        return bool(self.cognito_region and self.cognito_client_id)

    @classmethod
    def from_env(cls, env=os.environ) -> "Environment":
        api = (env.get("API_BASE_URL") or "").rstrip("/")
        if not api:
            raise EnvironmentIncomplete("API_BASE_URL is not set in rpi-edge/.env: the detection mode gets its "
                                        "configuration and models from the platform (or tools/dev_cloud.py)")
        return cls(
            api_base_url=api,
            cognito_region=env.get("COGNITO_REGION") or None,
            cognito_client_id=env.get("COGNITO_CLIENT_ID") or None,
            config_dir=Path(env.get("CONFIG_DIR", "/config")),
            state_dir=Path(env.get("STATE_DIR", "/state")),
            replay_dir=Path(env["REPLAY_DIR"]) if env.get("REPLAY_DIR") else None,
        )
