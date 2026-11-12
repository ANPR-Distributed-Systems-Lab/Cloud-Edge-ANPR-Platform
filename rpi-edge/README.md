# rpi-edge

Code of the edge node, a Raspberry Pi 5 with the IMX477 camera, in one Docker image with two modes:

| Mode | What it does | Document |
|---|---|---|
| `collection` | Records full-resolution frames to a USB stick, controlled from a browser: the training data of ml-models | [DATA_COLLECTION.md](DATA_COLLECTION.md) |
| `detection` | Reads plates (detector + OCR on the Pi), buffers them and sends them to the platform in batches | [DETECTION.md](DETECTION.md) |

Setting up the Pi and the `rpi` Docker context: [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md).

## Choosing the mode

The mode is set in `rpi-edge/.env` on the machine you run `docker compose` from (gitignored; start from
`.env.example`):

```bash
cp .env.example .env    # then set EDGE_MODE=collection or EDGE_MODE=detection
```

Apply it (from `rpi-edge/`, Docker context `rpi`):

```bash
docker compose up -d --build
```

Both modes are the same service, so changing the mode recreates the one container, and only one process ever
holds the camera. Without a `.env` the Pi runs `collection`, as before. `docker compose logs -f` shows the JSON
logs of whichever mode runs.

`main.py` reads `EDGE_MODE` and starts `collection.main` or `detection.main`. Both modes keep their state in Docker
volumes, so a mode switch or a rebuild loses nothing: `rpi-edge-config` (`/config`: the settings of both modes, the
device credentials, the copy of the device configuration) and `rpi-edge-state` (`/state`: the outbox and the
model cache of the detection mode).

## Layout

```
main.py             entry point: runs the mode chosen by EDGE_MODE
common/             shared by both modes: JSON logs, atomic JSON files, auto exposure, Pi health
collection/         the data collection mode (web UI in collection/ui/)
detection/          the detection mode: contract/, config/, vision/, rules/, delivery/, cloud/ (DETECTION.md, section 2)
tests/              unit tests (pytest), no camera, network or GPU
tools/              development tools: dev_cloud.py (the platform without AWS), stress_test.py (power supply test)
```

## Development

Code runs in the container on the Pi (it needs the camera); everything else is tested on the PC.

```bash
uv sync                 # Windows: set UV_CACHE_DIR to a disk with space first
uv run pytest
```

The tests use synthetic data only: no frames or plate texts. HTTP is replaced by a scripted fake (`tests/fakes.py`),
so the AWS paths (Cognito, ingest, device-management) are tested without AWS. The outbox tests use a real SQLite file
in a temporary directory, which is embedded and takes milliseconds. The tests also run on the Pi, inside the image,
which matters for `tests/vision/test_preprocess.py` (the preprocessing must give the pixels of ml-models there too,
within the ARM tolerance described in DETECTION.md, section 2):

```bash
docker compose run --rm --no-deps rpi-edge sh -c "uv pip install -q --python /opt/venv/bin/python pytest && /opt/venv/bin/python -m pytest -q -p no:cacheprovider tests"
```

`docker compose up --watch` syncs code changes into the running container and restarts it; dependency or Dockerfile
changes rebuild the image.

### The detection mode without AWS

`tools/dev_cloud.py` stands in for the platform: it serves the device configuration from
`tools/dev-device-config.json` (the defaults of device-management for this Pi; edit it to change thresholds,
flips or model versions, the Pi picks the change up at its next poll), the models from a directory laid out like
the models bucket, and accepts the batches of detections (printing counts, never plates). Run it on the PC and
reach it from the Pi through an SSH tunnel, so the Pi needs nothing installed and no firewall rule changes:

```bash
uv run python tools/dev_cloud.py <models-dir>     # port 8100; <models-dir>/detector/v2/model.onnx, ocr/v3/model.onnx, ocr/v3/plate_config.yaml
ssh -N -R 8100:127.0.0.1:8100 kamiljach@anpr-rpi.local
```

(`127.0.0.1`, not `localhost`: Windows' ssh tries `::1` first, and the server listens on IPv4 only.)

and in `.env`:

```
EDGE_MODE=detection
API_BASE_URL=http://localhost:8100
```

The container uses the host network, so `localhost` on the Pi is the end of the tunnel. The configuration and the
models are kept on the Pi, so it keeps detecting without the PC; the stand-in only has to be reachable when
batches go out (they wait in the outbox otherwise). `dev_cloud.py --ingest-status 503` (or `400`) shows the
retries (or the quarantine). The stand-in is for development only: against AWS, `API_BASE_URL` is the API Gateway
and the Cognito settings are filled in (`.env.example`).

### Replaying frames

`REPLAY_DIR` makes the detection mode read recorded JPEGs (e.g. a session of the collection mode, in name order,
looping) instead of the camera; everything after the camera is the same. It is how the mode is tested at the desk.
The directory must be inside the container, e.g. a session on the USB stick, mounted read-only by a one-off
container (on the Pi, with the service stopped so that only one process analyses):

```bash
docker run --rm --privileged --network host -v /dev:/dev -v rpi-edge_rpi-edge-config:/config \
  -v rpi-edge_rpi-edge-state:/state -e EDGE_MODE=detection -e STATE_DIR=/state/replay \
  -e API_BASE_URL=http://localhost:8100 \
  -e REPLAY_DIR=/mnt/usb/rpi-edge/<session> --entrypoint sh rpi-edge-rpi-edge \
  -c 'mkdir -p /mnt/usb && mount -o ro /dev/sda1 /mnt/usb && exec /opt/venv/bin/python main.py'
```

Delete `/state/replay` afterwards: its outbox holds plate texts.
