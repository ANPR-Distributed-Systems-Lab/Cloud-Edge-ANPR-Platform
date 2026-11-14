# Detection mode (rpi-edge)

The target mode of the edge node: the Raspberry Pi reads license plates from the camera and sends them to the
platform, with its position, the photo of the frame, its track and its health. Everything that has to reach the
platform goes through local queues (store-and-forward, root `CLAUDE.md`).

```
camera -> position of the frame (GNSS) -> detector -> geometry rule -> crop -> OCR -> per-frame rule -> cooldown
   |                                                                                          |
   | photo of the frame (JPEG on the SD card)                                                 v
   v                                                                          queue: detections -> POST /api/v1/ingest/detections
queue: images -> POST /api/v1/images/presigned-urls -> PUT to S3
GNSS track       -> queue: locations -> POST /api/v1/ingest/device-locations
health of device -> queue: metrics   -> POST /api/v1/device/metrics
```

Status (2026-11-13): everything above runs on the Pi against a development stand-in of the platform
(`tools/dev_cloud.py`, which checks the batches against the main rules of the ingest contracts), with the real GNSS
module, see [Measured on the Pi](#13-measured-on-the-pi). The AWS side exists in code (the models bucket and route in
`infrastructure/`, the endpoints and configuration fields in device-management, Cognito sign-in here) and is
covered by tests, but has not run against AWS yet, see [What is still missing](#14-what-is-still-missing). How to
switch the Pi into this mode is in [README.md](README.md).

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
| Queues | One SQLite queue (WAL, `synchronous=FULL`) on the SD card per stream: detections, locations, metrics, photos; only what is to be sent; 30 days at most (metrics 6) ([section 7](#7-queues-and-sending)) |
| Sending | Batches in the shape of each contract; section 4 of the ingest contract decides delete / quarantine / retry, the same code for every stream ([section 7](#7-queues-and-sending)) |
| Position | The GNSS module on UART0; a detection carries the last fix at the capture of its frame (at most 30 s old, its age in `fixAgeMs`); a frame without one is not read ([section 8](#8-position-and-the-track)) |
| Track | A point every `locationSampleSeconds` while moving, one a minute while stationary, to `device-locations` ([section 8](#8-position-and-the-track)) |
| Photos | The key of the photo is computed on the device, so a detection leaves at once; the JPEG of the full frame follows in the background ([section 9](#9-photos)) |
| Metrics | A measurement every `metricsSeconds`, queued like everything else ([section 10](#10-device-metrics)) |
| Alerts | The owner's alert list is polled into memory; an accepted detection of a listed plate shows on the LCD with three beeps ([section 11](#11-alerts-and-the-driver)) |
| Messages | Every document exchanged with the platform is a frozen dataclass in `detection/contract/`, checked against its contract on the way in ([section 2](#2-pipeline)) |

## 2. Pipeline

Code: `detection/`, one small module per step, grouped by what it deals with:

```
detection/
  main.py         assembles the parts and starts the threads (the docstring lists them)
  loop.py         the frame loop: capture, position, pipeline, queue, observers; a summary every 30 s
  pipeline.py     one frame and its position -> the events to buffer (detector, send rule, OCR)
  feedback.py     the LCD, the buzzer and the LED in the car: status screen, alert screen
  metrics.py      the device measurements; throughput.py counts the frames
  contract/       every message with the platform as a dataclass: configuration, models, alerts, ingest,
                  locations, metrics, images, problem; wire.py has the ids and timestamps they share
  config/         environment.py (rpi-edge/.env), store.py (the configuration and its copy on the device)
  gps/            nmea (sentences), tracker (fixes, state), source (module / fixed / none), serial_reader, recorder
  vision/         frame, camera, replay, preprocess, onnx (sessions), detector, ocr, models (loaded set, swap)
  rules/          plates (Polish format), send_rule (geometry, reading, cooldown), alerts (the alert list)
  delivery/       queue (SQLite), queues (the four queues and their streams), sender (batches), answers,
                  backoff, photos (JPEG encoder), uploads (photo upload)
  cloud/          transport (HTTP), cognito, api (token, trace id, health), config_poll, model_store,
                  model_updater, alert_poll
```

What goes where, by type (all in `detection/contract/`):

| Type | Direction | Endpoint | Used by |
|---|---|---|---|
| `DeviceConfiguration` | in | `GET /api/v1/device/config` | `config/store.py`, then every part reads `configuration.current` |
| `DeviceModels` | in | `GET /api/v1/device/models` | `cloud/model_store.py` |
| `AlertList` | in | `GET /api/v1/alerts` (operations-service) | `cloud/alert_poll.py`, kept by `rules/alerts.py` |
| `DetectionEvent`, `DetectionBatch` | out | `POST /api/v1/ingest/detections` | `pipeline.py` creates events, `delivery/queue.py` stores them, `delivery/sender.py` sends batches |
| `Location` | out | inside every detection | `gps/tracker.py` makes it from a fix, `pipeline.py` attaches it |
| `LocationPoint`, `LocationBatch` | out | `POST /api/v1/ingest/device-locations` | `gps/recorder.py` creates points, the same queue and sender |
| `DeviceMetric`, `MetricsBatch` | out | `POST /api/v1/device/metrics` | `metrics.py` creates measurements, the same queue and sender |
| `ImageUploadRequest`, `ImageUploadUrls` | out, in | `POST /api/v1/images/presigned-urls` | `delivery/uploads.py` |
| `Problem` | in | any error answer | the senders (quarantine by `fields[].index`), the pollers and the model store (logged codes) |

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
| Position | `gps/source.py` | The fix of the GNSS module at the capture of the frame, before the detector's results are read ([section 8](#8-position-and-the-track)) |
| Event | `pipeline.py`, `contract/ingest.py` | One `DetectionEvent` per accepted plate, in the shape of `docs/api/ingest-detections.md`, with the key of its photo and its position |

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

0. **A position, before everything else.** The platform requires a position with every detection, and the position
   at the capture of the frame cannot be recovered later, so a frame without a fix (none within 30 s of its
   capture, [section 8](#8-position-and-the-track)) is not read at all: its detections are counted as `no_location`.
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
`near_edge`, `bad_corners`, `no_location`, `no_text`, `unreadable`, `bad_format`, `low_confidence`, `cooldown`), with the
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

## 7. Queues and sending

**Queues** (`delivery/queue.py`, `delivery/queues.py`, one SQLite file each in `/state/outbox/`):

| Queue | Item | Kept | Sent to |
|---|---|---|---|
| `detections` | `DetectionEvent` | 30 days, 100 000 rows | `POST /api/v1/ingest/detections` |
| `locations` | `LocationPoint` | 30 days, 200 000 rows | `POST /api/v1/ingest/device-locations` |
| `metrics` | `DeviceMetric` | 6 days (the platform refuses older), 20 000 rows | `POST /api/v1/device/metrics` |
| `images` | `ImageJob`: the frame id, its capture time, the path of the JPEG | 30 days, 2 000 rows | presigned URL, then S3 ([section 9](#9-photos)) |

- An item is stored as the document that is sent and read back into the same dataclass. The items of one frame are
  added in one committed transaction with `synchronous=FULL`, so they survive a power cut.
- Only what is to be sent is stored: no rejected readings (plates and coordinates are personal data). Items past
  the retention, and the oldest beyond the row limit, are dropped (`items_dropped` in the log).
- `<name>_quarantine` keeps what the platform refused for good (400, 413, 415) with the status and the error code,
  for diagnosis. Same limits.

**Senders** (`delivery/sender.py`): one `Sender` per JSON stream (detections, locations, metrics), one thread each,
the same code, told by a `Stream` what to send where:

- A batch leaves when the stream's batch size of items wait (`batching.detectionsBatchSize` 20,
  `batching.locationsBatchSize` 100) or the oldest has waited `batching.maxBatchDelaySeconds` (10 s). Metrics leave
  at once, up to 100 per request (the contract), since one measurement is made per interval.
- The batch id (UUID v5 of the item ids, so a resend reuses it without storing it) is also the `X-Trace-Id` of the
  request. `detectionId` (UUID v7) is the trace id of a detection. Metrics use a stable id of their `recordedAt`s.
- Outcomes, as the ingest contract (section 4) asks, decided in `delivery/answers.py` for every sender and the
  photo uploader:

  | Answer | Edge |
  |---|---|
  | 2xx | delete the batch |
  | 400, 413, 415 | quarantine the items named by `fields[].index`, or the whole batch when none is named; send the rest again at once |
  | 401 | the token is renewed and the request retried once (`cloud/api.py`); if it fails again, back off |
  | 403 | not a device token: a configuration problem; keep the data, try again in 10 min, log an error |
  | 429, 5xx, no answer, other statuses | keep the batch, back off exponentially (2 s doubling up to 5 min, with jitter, `delivery/backoff.py`), honour `Retry-After` |

- The device has no battery-backed clock. Without network after a cold start, `detectedAt` may be wrong until the
  time syncs, and the platform may refuse such items (`TIMESTAMP_TOO_OLD` / `TIMESTAMP_IN_FUTURE`, quarantined).
  The GNSS module gives the true time: when the clock of the device differs from it by 5 s or more, the tracker logs
  `clock_skew` once a minute.

## 8. Position and the track

The GNSS module (Waveshare LC76G) is wired to UART0 (`RASPBERRY_PI_SETUP.md`, "Pins in use"), is read at 115200 baud
from `GPS_DEVICE` (`/dev/ttyAMA0`) and needs no commands: it sends NMEA sentences once a second. Decided 2026-11-13.

- **Parsing** (`gps/nmea.py`): RMC (time, position, speed, course), GGA (satellites used, HDOP), GSA (fix type) and
  GSV (satellites in view) only; a sentence with a wrong checksum or a missing field is ignored, so noise never
  becomes a position. `gps/serial_reader.py` feeds `gps/tracker.py` and reopens the port when it fails (the first
  failure is logged once).
- **A fix** (`gps/tracker.py`): a valid RMC. Its accuracy is HDOP x 5 m (`accuracyM`), its heading is dropped below
  2 m/s (7 km/h), where the course over ground is noise (a stationary antenna near a window shows up to 0.7 m/s).
  The fixes of the last minute are kept with the device time at which they arrived.
- **The position of a frame** (`gps/source.py`, `locate()`): the latest fix that arrived at or before the capture of
  the frame, if it is at most 30 s older; `fixAgeMs` is its age at the capture. Without such a fix the frame is
  not read (rejection `no_location`, [section 3](#3-send-rule)): waiting would not help, since the position at that
  moment cannot be reconstructed later, and a position older than 30 s is not the position of a moving car.
- **The track** (`gps/recorder.py`): the latest fresh fix every `intervals.locationSampleSeconds` (5 s) while the
  speed is 2 m/s or more, one point a minute while stationary, none without a fresh fix. The platform refuses a
  point without a position.
- **Sources** (`GPS_DEVICE`, `GPS_FIXED_LOCATION` in `.env`): the module; a fixed `lat,lon` for development and for
  replaying recordings (no fix needed); or neither, then no frame is ever read and the log says why
  (`gps_not_configured`).
- Coordinates are personal data: they are never logged. The status screen shows only the state: `GPS 3D 13` (fix and
  satellites used), `GPS nofix 7` (satellites in view), `GPS --` (the module is silent).

## 9. Photos

The detection carries the S3 key of the photo of its frame, `images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg`
(`contract/images.py`). The layout is fixed by the contract, so the device computes the key itself and the detection
leaves at once, without waiting for the upload (decided 2026-11-13; the contracts say so in
`docs/api/ingest-detections.md`, section 7). The photo follows in the background:

1. **Save** (`delivery/photos.py`): the frame loop hands every frame that produced detections to the encoder thread,
   which writes the JPEG (full resolution, quality 90, 1.5-3 MB in the tests) to `/state/frames/<frameId>.jpg`
   (through a `.part` file, so a power cut never leaves half a photo) and adds a row to the `images` queue. When the
   encoder is three frames behind, further photos are not saved (`photo_not_saved`): a detection without a photo is
   better than a slower detection. The size of the photo is to be decided later.
2. **Upload** (`delivery/uploads.py`): in batches of `batching.imageUrlsBatchSize` the uploader asks device-management
   for presigned URLs. For each frame the key in the answer must be the key the device computed, otherwise the photo is
   quarantined (`image_quarantined`, reason `IMAGE_KEY_MISMATCH`). Then it PUTs the file with
   `Content-Type: image/jpeg` and no `Authorization` header (the URL carries its own signature). A failed or refused
   PUT keeps the file and the row; the next attempt asks for fresh URLs, which also covers an expired one.
3. **Delete**: a file is deleted with its row, whether it was uploaded, quarantined or dropped by the retention.

## 10. Device metrics

`metrics.py` takes a measurement after the start and then every `intervals.metricsSeconds` (60 s): CPU temperature,
CPU and RAM load (psutil), frames analysed per second since the previous measurement, the length of the detection,
location and photo queues, free space of the state volume, uptime, and the GNSS state (`NONE` / `FIX_2D` / `FIX_3D`
and satellites used). It queues the measurement like everything else, so after an outage they go out together. Values
are brought into the ranges of the contract before sending, because one invalid measurement makes the service refuse
the whole batch. Without a readable CPU temperature (a development PC) no measurement is made: the contract requires
it, and a made-up value would chart as a fact. View 4 shows the device online while its latest measurement is
young, so without metrics a working device would look offline.

## 11. Alerts and the driver

Decided 2026-11-12, in the shape proposed then.

**Alert list** (`cloud/alert_poll.py`, `rules/alerts.py`). The device polls `GET /api/v1/alerts` of
operations-service every `intervals.alertsPollSeconds` with `If-None-Match`; a device gets every alert of its
owner in one answer (`contract/alerts.py`: alert id, plate, alert text). The list holds plates, so it is kept in
memory only: never on the SD card, never in the log. After a restart without network there are no alerts until
the first successful poll (the screen shows `AL ?`).

**Matching.** Only accepted detections are matched, after the send rule and the cooldown, so a passing car raises
one alert, from a reading good enough to be sent. A match logs `alert_matched` with the `traceId` of the detection
and the `alertId`, never the plate. The detection itself is sent as any other.

**Feedback** (`detection/feedback.py`, peripherals in `common/peripherals.py`, the same as the collection mode):

```
DET 1.6fps D2 O3        frames per second (last 10 s), model versions; WAIT CONFIG / WAIT MODELS before
NET ok      Q 3         the platform answers (ok / offline / --), detections waiting to be sent
GPS 3D 13   AL 5        the GNSS fix and satellites used, alerts on the list (? before the first list)
192.168.1.20 54C        the IP, the CPU temperature
```

- An alert replaces the status screen for 15 s: `*** ALERT ***`, the plate, the alert text over two lines (the LCD
  has no Polish letters: ą becomes a, ł becomes l), and the buzzer gives three beeps of 0.4 s.
- One short beep when the first frame is analysed: the mode is running. The LED is on while frames are analysed.
- `NET` follows the latest request to the platform (`cloud/api.py`, `CloudHealth`): offline after a request
  without an answer, ok after one with any answer.
- Every part is optional: without an LCD, buzzer or LED the mode works the same and only the log tells.

## 12. Logs

JSON lines (`common/jsonlog.py`: `ts`, `level`, `event`, fields), per the project convention. In the business flow
`traceId` is the `detectionId` (`detection_buffered`) or the id of the batch (`batch_sent`, `batch_failed`,
`items_quarantined`, each with `stream`: detections, locations or metrics), and `alert_matched` carries the
`traceId` of the detection. Plate texts (also of the alert list), coordinates, frames, passwords, tokens and the
query strings of presigned URLs are never logged. `detection_summary` every 30 s: frames, fps, events, rejections
per reason (`no_location` among them), median timings, pending and quarantined detections, CPU temperature.

## 13. Measured on the Pi

Pi 5 (8 GB), detector v2 at 1280x960 and OCR v3, both FP32 on ONNX Runtime with 4 threads, 2026-11-12:

| Run | fps | Detector (resize + model) | OCR per frame | CPU |
|---|---|---|---|---|
| Live camera, no plates in view | 1.7 | 516-527 ms | - | 47 °C |
| Replay of a val session from the USB stick (`REPLAY_DIR`) | 1.4-1.5 | 488 ms | 80-146 ms (all plates of the frame) | 55-56 °C |

- In the replay, every stage of the send rule fired (`too_small`, `near_edge`, `unreadable`, `bad_format`,
  `low_confidence`, `cooldown`), and the accepted detections reached the mock ingest in batches (202).
- After the move to the cloud-only configuration, with alerts and feedback (2026-11-13, on the Pi through the
  SSH tunnel to `tools/dev_cloud.py`): 175 tests pass inside the image; a replay downloads the configuration, the
  alert list and the three model files and sends its detections (1.4-1.5 fps, 202); with a plate of that replay put
  on the alert list, the next replay raised `alert_matched`; on the live camera (1.6-1.75 fps) a new detector
  version in the configuration was downloaded and swapped in without a change in the frame rate; with the tunnel
  closed, a restart ran on the copies of the configuration and the models. The collection mode still starts with
  the shared peripherals.
- With the position, photos, track and metrics (2026-11-13, on the Pi through the SSH tunnel to `tools/dev_cloud.py`,
  with the real GNSS module, its antenna behind a window): 248 tests pass inside the image (ARM); a replay of a val
  session ran 150 s at 1.3-1.5 fps with 8 detections in 5 batches (202), 15 measurements (204), 6 track points
  (202), 5 requests for photo URLs and 7 photos uploaded (11 MB), all of it accepted by the checks of the stand-in
  (required fields, ranges, the format of `imageKey`); on the live camera, 1.6 fps with the same threads running;
  the LCD and the buzzer opened without errors (not seen by the tester). The 6 track points instead of the 3 a
  stationary device should record led to the moving threshold of 2 m/s.
- Store-and-forward: with the mock stopped, detections stayed in the outbox (`batch_not_sent`, backoff). After a
  `docker kill` (no clean shutdown) the container came back with them (`pending: 4`), and they went out in one
  batch once the mock was back.
- The analysis rate is below the 2-3 fps assumed in ML_ASSUMPTIONS: these numbers belong to the Pi benchmark of
  the detector input size (ml-models roadmap, item 6). Cheaper inference (INT8, a smaller input, fewer OCR threads)
  is not tried yet.

## 14. What is still missing

- **First run against AWS**: `terraform apply` of the models bucket and route, device-management deployed with the
  new contract, models v2 and v3 published, the device paired (`infrastructure/scripts/create_device.py`) and its
  credentials placed on the Pi. The Cognito sign-in and the real ingest, device-locations and metrics endpoints have
  only run against fakes and the stand-in. The deployed ingest Lambda and operations-service may be older than the
  contracts here (alerts for devices, photo URLs in detections).
- **Photos**: the size of the uploaded photo (full frame now); frames of a power cut that never reached the queue
  leave a detection without a photo.
- **GNSS**: time from the module to correct the clock of the device (only a warning now); the antenna in the car.
- **ml-models**: the final thresholds and detector input size (the `detection_summary` timings on the Pi feed that
  benchmark). The analysis rate is 1.4-1.7 fps.
- **Later**: tracking a plate across frames, rotation of the device password (`docs/identity-and-access.md`).
