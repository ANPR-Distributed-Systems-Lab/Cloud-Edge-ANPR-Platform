"""anpr-publish-model: publishes a model version to the models bucket, from which the edge devices download it.

    uv run anpr-publish-model detector v2 --bucket <models bucket> [--profile <AWS profile>]

The version is the run: runs/detector/<run>/model.onnx (from anpr-export-detector), or runs/ocr/<run>/model.onnx
and plate_config.yaml (from anpr-train-ocr). Their files go to models/<model>/<version>/ and, last,
release.json lists them with their SHA-256 and size: device-management-service treats a version as published
once release.json exists, so a half-finished upload is never offered to a device. A version is published once;
publishing it again is refused. The bucket name is the Terraform output models_bucket_name
(infrastructure/envs/dev); the upload uses the AWS credentials of the developer.

Publishing does not change any device: a device runs the versions named in its configuration (models.detector,
models.ocr in device-management), and switches when that configuration changes.
"""
import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .paths import RUNS_DIR

# What the edge node needs of each model (rpi-edge/detection/cloud/model_store.py).
RELEASE_FILES = {"detector": ("model.onnx",), "ocr": ("model.onnx", "plate_config.yaml")}
RELEASE_FILE = "release.json"
DEFAULT_REGION = "eu-central-1"


@dataclass(frozen=True)
class ReleaseFile:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Release:
    """release.json, as device-management-service reads it (internal/models/ModelRelease)."""
    model: str
    version: str
    published_at: datetime
    files: tuple[ReleaseFile, ...]

    def to_json(self) -> bytes:
        document = {
            "model": self.model,
            "version": self.version,
            "publishedAt": self.published_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "files": [{"name": f.name, "sha256": f.sha256, "sizeBytes": f.size_bytes} for f in self.files],
        }
        return json.dumps(document, indent=2).encode("utf-8")


def key(model: str, version: str, file_name: str) -> str:
    """The key layout of the models bucket (infrastructure/envs/dev/models.tf)."""
    return f"models/{model}/{version}/{file_name}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(model: str, version: str, run: Path, now: datetime) -> Release:
    """The release of a run; every file the edge node needs must be there."""
    missing = [name for name in RELEASE_FILES[model] if not (run / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{run} has no {', '.join(missing)}"
                                + (" (run anpr-export-detector first)" if model == "detector" else ""))
    files = tuple(ReleaseFile(name, sha256_of(run / name), (run / name).stat().st_size) for name in RELEASE_FILES[model])
    return Release(model, version, now, files)


def is_published(s3, bucket: str, model: str, version: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3.head_object(Bucket=bucket, Key=key(model, version, RELEASE_FILE))
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def publish(s3, bucket: str, release: Release, run: Path) -> None:
    """Uploads the files, then release.json. Refuses a version that is already published."""
    if is_published(s3, bucket, release.model, release.version):
        raise FileExistsError(f"{release.model} {release.version} is already published; a version never changes")
    for file in release.files:
        s3.upload_file(str(run / file.name), bucket, key(release.model, release.version, file.name))
    s3.put_object(Bucket=bucket, Key=key(release.model, release.version, RELEASE_FILE), Body=release.to_json(),
                  ContentType="application/json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", choices=sorted(RELEASE_FILES))
    parser.add_argument("version", help="the run name, e.g. v2; it becomes the published version")
    parser.add_argument("--bucket", required=True, help="Terraform output models_bucket_name")
    parser.add_argument("--profile", help="AWS profile (default: the default credentials chain)")
    parser.add_argument("--region", default=DEFAULT_REGION)
    args = parser.parse_args()

    import boto3

    run = RUNS_DIR / args.model / args.version
    release = build_release(args.model, args.version, run, datetime.now(UTC))
    s3 = boto3.Session(profile_name=args.profile, region_name=args.region).client("s3")
    publish(s3, args.bucket, release, run)
    for file in release.files:
        print(f"{key(release.model, release.version, file.name)}  {file.size_bytes} B  sha256 {file.sha256}")
    print(f"published {release.model} {release.version}; set models.{release.model} = {release.version} in the "
          "configuration of a device to run it")


if __name__ == "__main__":
    main()
