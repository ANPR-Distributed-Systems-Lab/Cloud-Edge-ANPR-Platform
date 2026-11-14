"""Photos of the frames of detections: their S3 key, and the upload URLs of device-management.

  POST /api/v1/images/presigned-urls   {"frames": [{"frameId", "capturedAt"}, ...]}
                                       -> {"uploads": [{"frameId", "imageKey", "uploadUrl", "expiresAt"}, ...]}

The key of a photo is fixed by the contract: images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg, with the UTC date
of the capture (docs/api/ingest-detections.md). The device computes it, so a detection can leave before its photo
is uploaded; device-management returns the same key for the same frame, and the uploader checks that it does.
"""
from dataclasses import dataclass
from datetime import UTC, datetime

from detection.contract.configuration import UUID
from detection.contract.parsing import matching, parse
from detection.contract.wire import iso_ms, stable_id

CONTENT_TYPE = "image/jpeg"  # the upload URL signs exactly this Content-Type
IMAGE_KEY = rf"images/{UUID}/\d{{4}}/\d{{2}}/\d{{2}}/{UUID}\.jpg"


def image_key(device_id: str, frame_id: str, captured_at: datetime) -> str:
    return f"images/{device_id}/{captured_at.astimezone(UTC):%Y/%m/%d}/{frame_id}.jpg"


@dataclass(frozen=True)
class FrameToUpload:
    frame_id: str
    captured_at: datetime

    def to_document(self) -> dict:
        return {"frameId": self.frame_id, "capturedAt": iso_ms(self.captured_at)}


@dataclass(frozen=True)
class ImageUploadRequest:
    frames: tuple[FrameToUpload, ...]

    @property
    def trace_id(self) -> str:
        return stable_id(f.frame_id for f in self.frames)

    def to_document(self) -> dict:
        return {"frames": [f.to_document() for f in self.frames]}


@dataclass(frozen=True)
class ImageUpload:
    frame_id: str = matching(UUID)
    image_key: str = matching(IMAGE_KEY)
    upload_url: str = matching(r"\S+")  # presigned PUT URL: it carries its own signature, no Authorization header
    expires_at: str = matching(r".+")


@dataclass(frozen=True)
class ImageUploadUrls:
    uploads: tuple[ImageUpload, ...]  # one per requested frame, in the order of the request

    @classmethod
    def from_document(cls, document) -> "ImageUploadUrls":
        """Raises ContractError naming every upload that breaks the contract."""
        return parse(cls, document)

    def for_frame(self, frame_id: str) -> ImageUpload | None:
        return next((u for u in self.uploads if u.frame_id == frame_id), None)
