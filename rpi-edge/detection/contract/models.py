"""Download URLs of the models of the device (GET /api/v1/device/models, DeviceModelsResponse).

device-management answers with the versions named in the configuration of the device; each file comes with
its SHA-256 and size, to check the download, and a presigned GET URL that is valid until expires_at.
"""
from dataclasses import dataclass

from detection.contract.configuration import MODEL_VERSION, UUID, ModelVersions
from detection.contract.parsing import ContractError, bounded, matching, parse

FILE_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"  # becomes a path in the model cache


@dataclass(frozen=True)
class ModelFile:
    name: str = matching(FILE_NAME)
    sha256: str = matching(r"[0-9a-f]{64}")
    size_bytes: int = bounded(0, 2**40)
    url: str = matching(r"\S+")  # absolute (S3), or relative to the models endpoint (tools/dev_cloud.py)
    expires_at: str = matching(r".+")


@dataclass(frozen=True)
class ModelDownload:
    version: str = matching(MODEL_VERSION)
    files: tuple[ModelFile, ...]

    def file(self, name: str) -> ModelFile:
        return next(f for f in self.files if f.name == name)


@dataclass(frozen=True)
class DeviceModels:
    device_id: str = matching(UUID)
    detector: ModelDownload
    ocr: ModelDownload

    @property
    def versions(self) -> ModelVersions:
        return ModelVersions(self.detector.version, self.ocr.version)

    @classmethod
    def from_document(cls, document, required_files: dict[str, tuple[str, ...]]) -> "DeviceModels":
        """Raises ContractError for a document outside the contract or without a file the device needs."""
        models = parse(cls, document)
        missing = [f"{name}.files has no {file_name}" for name, needed in required_files.items()
                   for file_name in needed if all(f.name != file_name for f in getattr(models, name).files)]
        if missing:
            raise ContractError(missing)
        return models
