# Detection mode (rpi-edge)

The target mode of the edge node: the Raspberry Pi reads license plates from the camera and sends them to the
platform. Frames never leave the device in this mode; only the detections do, through a local buffer
(store-and-forward, root `CLAUDE.md`).

```
camera (4056x3040 BGR) -> detector (ONNX) -> geometry rule -> rectified crop -> OCR (ONNX) -> per-frame rule
       -> cooldown per plate -> outbox (SQLite) -> sender -> POST /api/v1/ingest/detections (batches)
```

Status (2026-11-12): detection, OCR, the outbox and batch sending run on the Pi against a development stand-in
of the platform (`tools/dev_cloud.py`), see [Measured on the Pi](#9-measured-on-the-pi). The AWS side exists in
code (the models bucket and route in `infrastructure/`, `GET /api/v1/device/models` and the configuration fields in
device-management, Cognito sign-in here) and is covered by tests, but has not run against AWS yet, see
[What is still missing](#10-what-is-still-missing). How to switch the Pi into this mode is in [README.md](README.md).

## 1. Decisions

Decided 2026-11-12. Each line is the decision, the reason follows in the section it links.

| Area | Decision |
|---|---|
| Modes | One image and one Python project; `EDGE_MODE` in `rpi-edge/.env` picks `collection` or `detection` ([README](README.md)) |
| Runtime | ONNX Runtime on the CPU for both models; opencv pinned to the version of the golden preprocessing checksums |
| Preprocessing parity | Identical pixels to ml-models on x86; on the Pi the detector input is identical and the OCR crop within ±1 on at most 0.1 % of its values ([section 2](#2-pipeline)) |
| Send rule | Geometry before the OCR, then format / confidence / readability per frame, then a cooldown per plate text; no tracking yet ([section 3](#3-send-rule)) |
| Configuration | Only the device configuration of device-management (thresholds, model versions, camera, batching), which also holds the defaults; the device keeps a copy and has no settings of its own ([section 4](#4-configuration)) |
| Device identity | Cognito only (the `device` app client, username and password from pairing); no AWS keys on the device ([section 5](#5-device-account)) |
| Models | The versions are part of the configuration; device-management signs S3 download URLs for them; immutable versions, SHA-256 checked, cached on the SD card; a new version is swapped in without a restart ([section 6](#6-models)) |
| Buffer | SQLite (WAL, `synchronous=FULL`) on the SD card; only detections to be sent; 30 days at most ([section 7](#7-outbox-and-sending)) |
| Sending | Batches in the shape of the ingest contract; its section 4 decides delete / quarantine / retry ([section 7](#7-outbox-and-sending)) |
| Messages | Every document exchanged with the platform is a frozen dataclass in `detection/contract/`, checked against its contract on the way in ([section 2](#2-pipeline)) |

## 2. Pipeline

Code: `detection/`, one small module per step, grouped by what it deals with:

```
detection/
  main.py         assembles the parts and starts the threads
  loop.py         the frame loop: capture, pipeline, outbox, a summary every 30 s
  pipeline.py     one frame -> the events to buffer (detector, send rule, OCR)
  contract/       every message with the platform as a dataclass: configuration, models, ingest, problem
  config/         environment.py (rpi-edge/.env), store.py (the configuration and its copy on the device)
  vision/         frame, camera, replay, preprocess, onnx (sessions), detector, ocr, models (loaded set, swap)
  rules/          plates (Polish format), send_rule (geometry, reading, cooldown)
  delivery/       outbox (SQLite), sender (batches)
  cloud/          transport (HTTP), cognito, api (token, trace id), config_poll, model_store, model_updater
```

What goes where, by type (all in `detection/contract/`):

| Type | Direction | Endpoint | Used by |
|---|---|---|---|
| `DeviceConfiguration` | in | `GET /api/v1/device/config` | `config/store.py`, then every part reads `configuration.current` |
| `DeviceModels` | in | `GET /api/v1/device/models` | `cloud/model_store.py` |
| `DetectionEvent`, `DetectionBatch` | out | `POST /api/v1/ingest/detections` | `pipeline.py` creates events, `delivery/outbox.py` stores them, `delivery/sender.py` sends batches |
| `Problem` | in | any error answer | the sender (quarantine by `fields[].index`), the poller and the model store (logged codes) |

A document becomes a dataclass in `from_document()`, which checks every field against the range, choices or
pattern of its contract (`contract/parsing.py`) and names each problem; nothing else in the mode touches a raw
document. Tests mirror the folders under `tests/`.

| Step | Module | What it does |
|---|---|---|
| Capture | `vision/camera.py` | picamera2, full resolution `RGB888` (B, G, R in memory, the order of OpenCV and of the training frames). The sensor runs at 10 fps or more, so a capture waits briefly for a fresh frame; the loop analyses at most `camera.fps` frames per second. Software auto exposure of `common/autoexposure.py`, as in the collection mode. `vision/replay.py` replaces the camera with recorded frames (`REPLAY_DIR`, README) |
| Detector | `vision/detector.py` | `resize_for_detector()` to the model input (1280x960 for detector v2), YOLO11n-pose exported with NMS inside: rows of box, confidence, class and 4 corners |
| Crop | `vision/preprocess.py` | `rectify_plate()`: 128x64 RGB with an 8 % margin, from the corners on the full-resolution frame |
| OCR | `vision/ocr.py` | OCR v3 (fast-plate-ocr `cct-s-v2-global` with the readability head): text, the weakest slot probability, P(readable) |
| Rule | `rules/send_rule.py`, `rules/plates.py` | [Section 3](#3-send-rule) |
| Event | `pipeline.py`, `contract/ingest.py` | One `DetectionEvent` per accepted plate, in the shape of `docs/api/ingest-detections.md` |

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
so its configuration has `"camera": {"hflip": true, ..., "vflip": true}` (the default of device-management, which
matches the devices built so far).

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

The format check (`rules/plates.py`) implements `ml-models/PLATE_FORMAT.md`, written from the registration
regulation (Dz.U. 2022 poz. 1847 with the amendment of 2023) and checked against its text: ordinary car plates
(voivodeship letter, one of the 421 county codes of annex 13, a vehicle part in one of its layouts, no B, D, I, O,
Z in the vehicle part, no run of digits all zeros) and individual plates pass (decided 2026-11-12). Reduced,
motorcycle, temporary, historic, diplomatic and service plates fail and are not sent. 412 of the 415 labeled texts
pass (PLATE_FORMAT.md, last section).

The rejections are counted per reason in the `detection_summary` log line every 30 s (`too_small`,
`near_edge`, `bad_corners`, `no_text`, `unreadable`, `bad_format`, `low_confidence`, `cooldown`), with the
median timings. That is the data for tuning the thresholds, without any plate text in the logs.

## 4. Configuration

Two kinds, kept apart:

- **Environment** (`rpi-edge/.env`, see `.env.example`): where the platform is (`API_BASE_URL`, required in this
  mode), the Cognito region and the public `device` app client id (without them requests carry no token, for
  `tools/dev_cloud.py`). Fixed for the life of the container. Contains no secret.
- **The device configuration** of device-management (`GET /api/v1/device/config`, contract
  `DeviceConfigurationResponse`, here `contract/configuration.py`): the send rule thresholds (`ml`), the model
  versions (`models`), `plateCooldownSeconds`, `batching`, `intervals` and `camera` (exposure, white balance, fps,
  the flips of the mounting). **Decided 2026-11-12: it is the only source.** device-management holds the defaults
  of a new device (its `application.yaml`) and the owner edits them (View 4); the device has no defaults and no
  settings file of its own.

`config/store.py` keeps the last configuration received in `/config/device-config.json` (with its ETag), so after
a restart without network the device runs on that copy. `cloud/config_poll.py` asks every
`intervals.configPollSeconds` with `If-None-Match` (every 10 s until the first configuration arrives). A device
that has never received one waits: it does not open the camera. A configuration outside the contract is refused
as a whole and logged (`configuration_refused`, with the field problems), and the current one stays. A change
applies from the next frame; a change of the flips or the sensor rate restarts the camera, a change of `models`
starts the model update ([section 6](#6-models)).

During development the configuration comes from `tools/dev_cloud.py`, which serves `tools/dev-device-config.json`:
a stand-in with the service defaults for this Pi, used only until the device runs against the cloud.

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

Weights are never in git (root `CLAUDE.md`). Decided 2026-11-12:

**Distribution.**

- ml-models publishes a version with `anpr-publish-model <detector|ocr> <run>` into the models bucket
  (`infrastructure/envs/dev/models.tf`): the files under `models/{detector|ocr}/{version}/` and, last,
  `release.json` with the SHA-256 and size of each. A version is written once and never changed.
- Which versions a device runs is part of its configuration: `models.detector`, `models.ocr`. device-management
  refuses a configuration that names an unpublished version (400 `MODEL_NOT_PUBLISHED`).
- `GET /api/v1/device/models` (device token) answers with the versions of the device's configuration and, per
  file, the SHA-256, the size and a presigned GET URL valid for 30 minutes (`contract/models.py`). The device
  needs no AWS credentials. A configured version that is not published answers 409 `MODEL_NOT_PUBLISHED`.

```json
{"deviceId": "...",
 "detector": {"version": "v2", "files": [
   {"name": "model.onnx", "sha256": "<64 hex>", "sizeBytes": 11576350, "url": "https://...", "expiresAt": "..."}]},
 "ocr": {"version": "v3", "files": [
   {"name": "model.onnx", ...}, {"name": "plate_config.yaml", ...}]}}
```

A `url` may also be relative to the endpoint (`tools/dev_cloud.py` serves the files itself).

**On the device** (`state` volume, `/state/models/`, `cloud/model_store.py` and `cloud/model_updater.py`):

1. At startup the cached set of `current.json` is loaded at once, after its SHA-256 sums are checked again (a
   damaged SD card is caught), whatever its versions: the device detects without network.
2. The model updater (its own thread) compares the loaded versions with `models` of the configuration. When they
   differ it fetches the download URLs, downloads what is not cached to `.part` files, checks their SHA-256 and
   only then replaces `current.json`, so a power cut or a network error never leaves a half-installed set.
3. It loads the new set (ONNX Runtime sessions) while the frame loop goes on with the old one, then swaps them
   (`vision/models.py`): the next frame runs with the new models, without a restart and without a gap. The
   cooldown per plate survives the swap.
4. The current and the previous version of each model are kept, older ones are removed.
5. A failure keeps the running set and is retried after 5 s, doubling up to 5 min (`models_update_failed`).
   **Without network and without a cache** nothing can run: the mode waits and does not open the camera.

**Exports**: detector v2 is `ml-models/runs/detector/v2/model.onnx`, written by `anpr-export-detector`
(Ultralytics, `imgsz=[960, 1280]`, NMS inside with `conf=0.1, iou=0.7, max_det=100`; checked on 20 val frames: 39
detections in both ONNX Runtime and PyTorch, corners within 0.024 px). Output `(1, 100, 18)`. OCR v3 is
`ml-models/runs/ocr/v3/model.onnx` with its `plate_config.yaml`, as exported by `anpr-train-ocr`.

## 7. Outbox and sending

**Outbox** (`delivery/outbox.py`, `/state/outbox.sqlite3`):

- One row per accepted `DetectionEvent`, stored as the document that is sent and read back into the same
  dataclass (`QueuedDetection`). Each frame's detections are added in one
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
- After the move to the cloud-only configuration (same day, on the PC with `tools/dev_cloud.py` and a recorded
  session): configuration from the stand-in, the three model files downloaded and checked, then on a restart both
  taken from the copies on disk; 1.4-1.5 fps, batches accepted (202).
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
- **First run against AWS**: `terraform apply` of the models bucket and route, device-management deployed with
  the new contract, models v2 and v3 published, the device paired and its credentials placed on the Pi.
- **ml-models**: the final thresholds and detector input size (the `detection_summary` timings on the Pi feed that
  benchmark).
- **Device**: metrics (`POST /api/v1/device/metrics`), alerts, LCD / buzzer feedback in this mode.
