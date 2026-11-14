"""Where the platform is: rpi-edge/.env, passed in by docker compose, fixed for the life of the container."""
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = "/api/v1/device/config"
MODELS_PATH = "/api/v1/device/models"
ALERTS_PATH = "/api/v1/alerts"
INGEST_PATH = "/api/v1/ingest/detections"
LOCATIONS_PATH = "/api/v1/ingest/device-locations"
METRICS_PATH = "/api/v1/device/metrics"
IMAGE_URLS_PATH = "/api/v1/images/presigned-urls"
DEFAULT_GPS_BAUD = 115200  # the default of the Waveshare LC76G


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
    gps_device: str | None = None  # serial port of the GNSS module, e.g. /dev/ttyAMA0
    gps_baud: int = DEFAULT_GPS_BAUD
    gps_fixed_location: tuple[float, float] | None = None  # (lat, lon) for development and replay, instead of a module

    def url(self, path: str) -> str:
        return self.api_base_url + path

    @property
    def config_url(self) -> str:
        return self.url(CONFIG_PATH)

    @property
    def models_url(self) -> str:
        return self.url(MODELS_PATH)

    @property
    def alerts_url(self) -> str:
        return self.url(ALERTS_PATH)

    @property
    def ingest_url(self) -> str:
        return self.url(INGEST_PATH)

    @property
    def locations_url(self) -> str:
        return self.url(LOCATIONS_PATH)

    @property
    def metrics_url(self) -> str:
        return self.url(METRICS_PATH)

    @property
    def image_urls_url(self) -> str:
        return self.url(IMAGE_URLS_PATH)

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
            gps_device=env.get("GPS_DEVICE") or None,
            gps_baud=int(env.get("GPS_BAUD") or DEFAULT_GPS_BAUD),
            gps_fixed_location=_fixed_location(env.get("GPS_FIXED_LOCATION")),
        )


def _fixed_location(value: str | None) -> tuple[float, float] | None:
    """'52.229676,21.012229' to (lat, lon); anything else is a mistake in .env and stops the mode with a message."""
    if not value:
        return None
    try:
        lat, lon = (float(part) for part in value.split(","))
    except ValueError:
        raise EnvironmentIncomplete(f"GPS_FIXED_LOCATION must be 'lat,lon', not {value!r}") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat, lon) == (0, 0):
        raise EnvironmentIncomplete("GPS_FIXED_LOCATION is not a valid position")
    return lat, lon
