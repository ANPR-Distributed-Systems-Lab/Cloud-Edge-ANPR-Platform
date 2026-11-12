# Detection mode (rpi-edge)

The target mode of the edge node: the Raspberry Pi reads license plates from the camera and sends them to the
platform. Frames never leave the device in this mode; only the detections do, through a local buffer
(store-and-forward, root `CLAUDE.md`).

```
camera (4056x3040 BGR) -> detector (ONNX) -> geometry rule -> rectified crop -> OCR (ONNX) -> per-frame rule
       -> cooldown per plate -> outbox (SQLite) -> sender -> POST /api/v1/ingest/detections (batches)
```

Status (2026-11-12): detection, OCR, the outbox and batch sending run on the Pi against development servers
(`tools/`), see [Measured on the Pi](#9-measured-on-the-pi). The AWS parts (Cognito sign-in, the real ingest,
the model manifest and the configuration of device-management) are implemented and covered by unit tests, but
not yet run against AWS, see [What is still missing](#10-what-is-still-missing). How to switch the Pi into this
mode is in [README.md](README.md).

## 1. Decisions

Decided 2026-11-12. Each line is the decision, the reason follows in the section it links.

| Area | Decision |
|---|---|
| Modes | One image and one Python project; `EDGE_MODE` in `rpi-edge/.env` picks `collection` or `detection` ([README](README.md)) |
| Runtime | ONNX Runtime on the CPU for both models; opencv pinned to the version of the golden preprocessing checksums |
| Preprocessing parity | Identical pixels to ml-models on x86; on the Pi the detector input is identical and the OCR crop within ±1 on at most 0.1 % of its values ([section 2](#2-pipeline)) |
| Send rule | Geometry before the OCR, then format / confidence / readability per frame, then a cooldown per plate text; no tracking yet ([section 3](#3-send-rule)) |
| Settings | Defaults < local `/config/detection.json` < the device configuration polled from device-management, with field names of its contract ([section 4](#4-configuration)) |
| Device identity | Cognito only (the `device` app client, username and password from pairing); no AWS keys on the device ([section 5](#5-device-account)) |
| Models | A manifest from device-management with presigned S3 GET URLs; immutable versions; SHA-256 checked; cached on the SD card, so the device works offline ([section 6](#6-models)) |
| Buffer | SQLite (WAL, `synchronous=FULL`) on the SD card; only detections to be sent; 30 days at most ([section 7](#7-outbox-and-sending)) |
| Sending | Batches in the shape of the ingest contract; its section 4 decides delete / quarantine / retry ([section 7](#7-outbox-and-sending)) |

## 2. Pipeline

Code: `detection/`, one small module per step, grouped by what it deals with:

```
detection/
  main.py         assembles the parts and starts the threads
  loop.py         the frame loop: capture, pipeline, outbox, a summary every 30 s
  pipeline.py     one frame -> the events to buffer (detector, send rule, OCR)
  config/         environment.py (rpi-edge/.env), schema.py (typed settings, contract ranges), settings.py (layers)
  vision/         frame, camera, replay, preprocess, onnx (sessions), detector, ocr
  rules/          plates (Polish format), send_rule (geometry, reading, cooldown)
  delivery/       events (ingest shape, ids), outbox (SQLite), sender (batches)
  cloud/          transport (HTTP), cognito, api (token, trace id), model_store, config_poll
```

Settings reach the code as immutable dataclasses (`settings.current.ml.ocr_min_confidence`); only `config/` sees
the documents with the field names of the contract. Tests mirror the folders under `tests/`.

| Step | Module | What it does |
|---|---|---|
| Capture | `vision/camera.py` | picamera2, full resolution `RGB888` (B, G, R in memory, the order of OpenCV and of the training frames). The sensor runs at 10 fps or more, so a capture waits briefly for a fresh frame; the loop analyses at most `camera.fps` frames per second. Software auto exposure of `common/autoexposure.py`, as in the collection mode. `vision/replay.py` replaces the camera with recorded frames (`REPLAY_DIR`, README) |
| Detector | `vision/detector.py` | `resize_for_detector()` to the model input (1280x960 for detector v2), YOLO11n-pose exported with NMS inside: rows of box, confidence, class and 4 corners |
| Crop | `vision/preprocess.py` | `rectify_plate()`: 128x64 RGB with an 8 % margin, from the corners on the full-resolution frame |
| OCR | `vision/ocr.py` | OCR v3 (fast-plate-ocr `cct-s-v2-global` with the readability head): text, the weakest slot probability, P(readable) |
| Rule | `rules/send_rule.py`, `rules/plates.py` | [Section 3](#3-send-rule) |
| Event | `pipeline.py`, `delivery/events.py` | One detection per accepted plate in the shape of `docs/api/ingest-detections.md` |

`vision/preprocess.py` is a copy of `ml-models/src/anpr_ml/common/preprocess.py`. `tests/vision/test_preprocess.py` holds
the golden checksums of `ml-models/tests/test_common.py`. If the functions change in ml-models, they change here
in the same way. Measured on the Pi 5 (decided 2026-11-12):

- `resize_for_detector()` (the detector input) is **bit-identical** on x86 and on the Pi.
- `rectify_plate()` (the OCR crop) is bit-identical on x86 only. On ARM, OpenCV's `warpPerspective` and `resize`
  take other SIMD paths, which move a few values by 1 (on 22 test plates at most 0.05 % of a crop's values, never
  more than 1). Rounding the transform matrix does not help, so this is accepted: irrelevant for the OCR, which was
  trained with a corner jitter of 1.5 % of the plate width. On ARM the test compares the crop with the x86
  reference crops in `tests/vision/golden/` (synthetic noise) within 1 level and 0.1 % of the values.

The camera stream uses the colour space of the recordings (`Sycc`: sRGB transfer, full range); the default of a
video configuration would be Rec709.

The camera must be mounted as during the recording of the training data. This Pi recorded with both flips on,
so its `/config/detection.json` sets `"camera": {"hflip": true, "vflip": true}`.

## 3. Send rule

The shape recommended by the ML analysis (`ml-models/ML_ASSUMPTIONS.md`, section 9). The thresholds are still
OPEN in ML; they are settings, not code.

1. **Geometry, before the OCR** (`ml.minPlateWidthPx`, default 70 px on the original frame;
   `ml.minEdgeMarginPx`, default 10 px). Narrower plates are not read reliably, and a plate cut by the frame edge
   gives a wrong crop (the exported model does not clip corners to the frame). The corners must also be
   clockwise and convex, the rule of the ingest Lambda, because one invalid detection rejects a whole batch.
2. **Per frame, after the OCR**: some text; P(readable) at least `ml.readableMinProbability` (0.80); a standard
   Polish plate (`rules/plates.py`); the weakest character at least `ml.ocrMinConfidence` (0.80). Detections below
   `ml.detectorMinConfidence` (0.40, the operating point of detector v2) never reach the rule.
3. **One event per plate**: the same text is not sent again within `plateCooldownSeconds` (60 s). The first
   good reading is sent at once. Plate texts of the cooldown stay in memory only.

Tracking a plate across frames with agreement between them is left out for now: at 2-3 fps an oncoming car moves
about 14 m between frames, which makes tracking unreliable, and the ML analysis found that agreement across frames
added nothing for the OCR with rejects. It can be added in `pipeline.py` when real drives show repeated wrong reads.

The format check follows the standard patterns (2- or 3-letter county code, then the vehicle part patterns of
the registration regulation). It is **not verified** against the official text yet; the verified rules
document is an open item of ml-models. Custom and special plates fail it and are not sent.

The rejections are counted per reason in the `detection_summary` log line every 30 s (`too_small`,
`near_edge`, `bad_corners`, `no_text`, `unreadable`, `bad_format`, `low_confidence`, `cooldown`), with the
median timings. That is the data for tuning the thresholds, without any plate text in the logs.

## 4. Configuration

Two kinds, kept apart:

- **Environment** (`rpi-edge/.env`, see `.env.example`): where the platform is (`API_BASE_URL`), the Cognito
  region and the public `device` app client id, and development overrides (`INGEST_URL`, `MODELS_MANIFEST_URL`).
  Fixed for the life of the container. Contains no secret.
- **Settings**: thresholds, batching, camera. Three layers, each overriding the one before (`config/settings.py`):
  1. the defaults in the code,
  2. `/config/detection.json` on the device, edited by hand (the camera mounting, experiments),
  3. the device configuration of device-management (`GET /api/v1/device/config`, polled every
     `intervals.configPollSeconds` with `If-None-Match`), cached in `/config/cloud-config.json`, so it also
     applies after a restart without network. Polling runs only when `API_BASE_URL` is set.

The field names are those of the device configuration contract (`device-management-api.yaml`): `ml`,
`batching`, `plateCooldownSeconds`, `intervals`, `camera` (exposure and white balance with the upper-case enums
of the contract). A layer that breaks a range of the contract is ignored as a whole and logged
(`settings_layer_ignored`), so a typo never leaves a half-applied configuration. Settings change live; a change
of the flips or the sensor rate restarts the camera.

Two fields are not in the contract yet: `ml.readableMinProbability` and `ml.minEdgeMarginPx` (local defaults
apply until device-management adds them). The contract's default thresholds (detector 0.5, OCR 0.6, width 60 px)
also differ from the ML starting points used here (0.40, 0.80, 70 px). Once the device polls the cloud, the
cloud values win.

Example `/config/detection.json` on this Pi:

```json
{"camera": {"hflip": true, "vflip": true}}
```

## 5. Device account

- The Pi is a user of the Cognito pool in the group `devices`, created by device-management at pairing
  (`docs/identity-and-access.md`). It signs in with `USER_PASSWORD_AUTH` on the public `device` app client,
  keeps the access token and the refresh token in memory, renews the access token 2 minutes before it expires
  with `REFRESH_TOKEN_AUTH`, and falls back to the password when the refresh token is refused (`cloud/cognito.py`).
- The access token goes only to URLs under `API_BASE_URL` (`cloud/api.py`): never to a presigned S3 URL (which carries
  its own signature) or to a development override. After a 401 the token is renewed and the request retried once.
- There are **no AWS credentials on the device**. Everything goes through API Gateway with the Cognito token,
  and S3 is reached only through presigned URLs that the platform signs.
- The username and password are stored on the Pi only, in the config volume, as
  `/config/device-credentials.json` (`{"username": "...", "password": "..."}`). They never go into the
  repository, `.env` or an image. To place them after pairing (from `rpi-edge/`, Docker context `rpi`):

  ```bash
  docker compose cp device-credentials.json rpi-edge:/config/device-credentials.json
  ```

  then delete the local file. Rotation and token lifetimes remain open points of `docs/identity-and-access.md`.

## 6. Models

Weights are never in git (root `CLAUDE.md`). The device downloads the current models at startup.

**Distribution (target).**

- A dedicated S3 bucket for models, with immutable keys `models/{detector|ocr}/{version}/{file}`.
  A version is never overwritten; a new model is a new version.
- A pointer to the current version of each model, written by the publishing step (ml-models).
- device-management answers `GET /api/v1/device/models` (device token) with the manifest of the current set. Per
  file it gives the SHA-256, the size and a presigned GET URL (as it already does for image uploads). This way
  the device needs no AWS credentials.

The manifest the device expects (`cloud/model_store.py`):

```json
{
  "models": {
    "detector": {"version": "v2", "files": {
      "model.onnx": {"sha256": "<64 hex>", "size": 11576350, "url": "https://<bucket>.s3...?X-Amz-Signature=..."}}},
    "ocr": {"version": "v3", "files": {
      "model.onnx": {"sha256": "<64 hex>", "size": 4881344, "url": "..."},
      "plate_config.yaml": {"sha256": "<64 hex>", "size": 314, "url": "..."}}}
  }
}
```

A `url` may also be relative to the manifest (the development server). The bucket, the pointer and the
endpoint do not exist yet; they belong to the infrastructure and device-management work.

**On the device** (`state` volume, `/state/models/`):

1. At startup the manifest is fetched. Files whose version is not cached are downloaded to a `.part` file and
   checked against their SHA-256. Only a complete set replaces `current.json`, so a power cut or a network error
   during a download never leaves a half-installed set.
2. The current and the previous version of each model are kept (a quick way back), older ones are removed.
3. **Without network** the cached set from `current.json` is used, after its SHA-256 sums are checked again
   (a damaged SD card is caught). **Without network and without a cache** the mode waits and retries (5 s,
   doubling up to 5 min) and does not start the camera.
4. Models are checked at startup only. A new model reaches the device with the next restart (every power-up in
   the car).

**Exports in use**: detector v2 was exported ad hoc for the first tests (from `ml-models`, outside git):

```bash
# in ml-models, on a copy of runs/detector/v2/weights/best.pt, so nothing is written into runs/
uv run python -c "from ultralytics import YOLO; YOLO('detector_v2.pt').export(format='onnx', imgsz=[960, 1280], nms=True, conf=0.1, iou=0.7, max_det=100, device='cpu')"
```

The output is `(1, 100, 18)`: on 15 val frames its detections and confidences match the PyTorch weights exactly
(corners differ only where PyTorch clips them to the frame). A proper export command and the publishing of models
belong to ml-models (its roadmap, item 8). OCR v3 is `ml-models/runs/ocr/v3/model.onnx` with its
`plate_config.yaml`, as exported by `anpr-train-ocr`.

## 7. Outbox and sending

**Outbox** (`delivery/outbox.py`, `/state/outbox.sqlite3`):

- One row per accepted detection, the body exactly as it is sent. Each frame's detections are added in one
  committed transaction with `synchronous=FULL`, so they survive a power cut.
- Only what is to be sent is stored: no frames, no rejected readings (plates are personal data).
- Rows older than 30 days are dropped (the ingest refuses them anyway), and each table keeps at most 100 000 rows,
  oldest dropped first (`detections_dropped` in the log).
- `quarantine` keeps the detections the ingest refused for good (400, 413, 415), with the status and the error
  code, for diagnosis. Same limits.

**Sender** (`delivery/sender.py`), one thread:

- A batch leaves when `batching.detectionsBatchSize` detections wait (20) or the oldest has waited
  `batching.maxBatchDelaySeconds` (10 s). Body: `{"batchId": ..., "detections": [...]}`.
- `batchId` is derived from the detection ids (UUID v5), so a resend of the same detections reuses it without
  storing it. It is also the `X-Trace-Id` of the request. `detectionId` (UUID v7) is the trace id of a detection.
- Outcomes, as the ingest contract (section 4) asks:

  | Answer | Edge |
  |---|---|
  | 2xx | delete the batch |
  | 400, 413, 415 | quarantine the detections named by `fields[].index`, or the whole batch when none is named; send the rest again at once |
  | 401 | the token is renewed and the request retried once (`cloud/api.py`); if it fails again, back off |
  | 403 | not a device token: a configuration problem; keep the data, try again in 10 min, log an error |
  | 429, 5xx, no answer, other statuses | keep the batch, back off exponentially (2 s doubling up to 5 min, with jitter), honour `Retry-After` |

- The device has no battery-backed clock. Without network after a cold start, `detectedAt` may be wrong until the
  time syncs, and the ingest may refuse such detections (`TIMESTAMP_TOO_OLD` / `TIMESTAMP_IN_FUTURE`, quarantined).

## 8. Logs

JSON lines (`common/jsonlog.py`: `ts`, `level`, `event`, fields), per the project convention. In the business flow
`traceId` is the `detectionId` (`detection_buffered`) or the `batchId` (`batch_sent`, `batch_failed`,
`detections_quarantined`). Plate texts, frames, passwords, tokens and the query strings of presigned URLs are never
logged. `detection_summary` every 30 s: frames, fps, events, rejections per reason, median timings, pending and
quarantined detections, CPU temperature.

## 9. Measured on the Pi

Pi 5 (8 GB), detector v2 at 1280x960 and OCR v3, both FP32 on ONNX Runtime with 4 threads, 2026-11-12:

| Run | fps | Detector (resize + model) | OCR per frame | CPU |
|---|---|---|---|---|
| Live camera, no plates in view | 1.7 | 516-527 ms | - | 47 °C |
| Replay of a val session from the USB stick (`REPLAY_DIR`) | 1.4-1.5 | 488 ms | 80-146 ms (all plates of the frame) | 55-56 °C |

- In the replay, every stage of the send rule fired (`too_small`, `near_edge`, `unreadable`, `bad_format`,
  `low_confidence`, `cooldown`), and the accepted detections reached the mock ingest in batches (202).
- Store-and-forward: with the mock stopped, detections stayed in the outbox (`batch_not_sent`, backoff). After a
  `docker kill` (no clean shutdown) the container came back with them (`pending: 4`), and they went out in one
  batch once the mock was back.
- The analysis rate is below the 2-3 fps assumed in ML_ASSUMPTIONS: these numbers belong to the Pi benchmark of
  the detector input size (ml-models roadmap, item 6). Cheaper inference (INT8, a smaller input, fewer OCR threads)
  is not tried yet.

## 10. What is still missing

- **Full ingest body**: `location` (GPS module) and `imageKey` (upload of the frame through
  `POST /api/v1/images/presigned-urls`) are required by the ingest contract. Until they exist, a batch sent to the
  real ingest is refused with 400 and quarantined. That is why the real endpoint has not been called yet.
- **Infrastructure**: the models bucket, the pointer to the current versions, `GET /api/v1/device/models` in
  device-management, and a device account to sign in with.
- **device-management contract**: `ml.readableMinProbability` and `ml.minEdgeMarginPx`, and defaults aligned
  with the ML starting points.
- **ml-models**: a detector export command and model publishing; the verified Polish plate rules; the final
  thresholds and detector input size (the `detection_summary` timings on the Pi feed that benchmark).
- **Device**: metrics (`POST /api/v1/device/metrics`), alerts, LCD / buzzer feedback in this mode.
