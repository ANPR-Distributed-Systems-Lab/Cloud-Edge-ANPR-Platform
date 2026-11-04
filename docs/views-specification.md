# Views 1–6 specification (source of truth)

Content translated from the architecture diagram `Inżynierka (2).drawio` (as of 12.10.2026).

**Rules:**
- This file is the source of truth for **what** each view does and which data it returns. The OpenAPI contract, the database model and the frontend must match it.
- A change of requirements = first change the diagram (agreed within the team), then this file, then the code.
- Deliberate deviations of the implementation from the diagram are listed in the "Deviations" section at the end, with a justification.

| View | Backend | Database | Frontend |
|---|---|---|---|
| 1 | MS2 Alerts-And-Views-Service | PostgreSQL | Angular |
| 2 | MS2 Alerts-And-Views-Service | PostgreSQL / PostGIS | Angular |
| 3 | MS2 Alerts-And-Views-Service | PostgreSQL / PostGIS | Angular |
| 4 | MS1 Device-Management-Service | DynamoDB | Angular |
| 5 | MS1 Device-Management-Service | DynamoDB | Angular |
| 6 | MS2 Alerts-And-Views-Service | PostgreSQL | Angular |

---

## View 1: ANPR search and analysis panel

**Functional description:**
- Central licence plate search with a suggestion mechanism (autocomplete).
- Precise filtering by plate number and time range (from–to).
- Results presented in two alternative forms: a dynamic map with location pins and a detailed list.
- A dedicated "Photo gallery" tab showing vehicle photos.

**Response payload:**
- account_id, device_id, plate, datetime, coordinates (GPS), s3_key

**Indexing requirements (PostgreSQL optimisation):**
- (detections) The query is optimised by the indexes: B-Tree (account_id), B-Tree (plate) and B-Tree (datetime).

---

## View 2: Radial analysis and route verification (PostGIS)

**Functional description:**
- Advanced event search based on a given geographic point and radius (e.g. within X metres of the coordinates) and a time range.
- Map visualisation of vehicle detection locations (ANPR photos) overlaid on the full, rendered route of the edge device (Raspberry Pi).
- The feature allows the path of a car to be reconstructed precisely, to confirm or rule out its presence at a given place and time.

**Response payload:**
- Detection data (ANPR): account_id, device_id, plate, datetime, coordinates (GPS), s3_key
- Device telemetry (GPS trace): account_id, device_coordinates, datetime

**Indexing requirements (PostgreSQL / PostGIS optimisation):**
- For ANPR data (detections): search optimised by the indexes B-Tree (account_id), spatial GiST (coordinates) and B-Tree (datetime).
- For the GPS trace (device_locations): search optimised by the indexes B-Tree (account_id), spatial GiST (coordinates) and B-Tree (datetime).

---

## View 3: Main dashboard and real-time monitoring (Live Feed)

**Functional description:**
- The main operational dashboard of the system, showing a map with the current position of the vehicle (Raspberry Pi).
- On the right there is a dynamic event list (Live Feed), refreshed in real time, showing the newest ANPR detections.
- The map shows the current position of the car and the rendered route for a given time window (e.g. the last 20 minutes), allowing ongoing supervision of the telemetry stream.

**Response payload:**
- Detection data (ANPR): account_id, device_id, plate, datetime, coordinates (GPS), s3_key
- Device telemetry (GPS trace): account_id, device_coordinates, datetime

**Indexing requirements (PostgreSQL / PostGIS optimisation):**
- For ANPR data (detections): search optimised by the indexes B-Tree (account_id) and B-Tree (datetime).
- For the GPS trace (device_locations): search optimised by the indexes B-Tree (account_id) and B-Tree (datetime).

---

## View 4: Raspberry Pi settings preview and editing

**Functional description:**
- An administration panel for remote management and configuration of edge devices.
- Allows previewing and changing the operational parameters of the RPi script, such as the cooldown before photos of the same plate can be sent again, the batch sizes used when sending local queues of vehicle scans and when requesting PreSigned URLs, and the detection thresholds of the machine learning (ML) model.

**Response payload:**
- device_id, plate_cooldown, batching_parameters, ML_model_parameters

**Indexing requirements (DynamoDB optimisation):**
- (device_configurations) Point reads and writes optimised directly by the primary key (Partition Key): PK - device_id (no Sort Key).

---

## View 5: Device status and hardware diagnostics panel

**Functional description:**
- A diagnostic screen showing, in real time, the current technical condition and operational performance of the edge device. It shows the network connection status (heartbeat), the fill level and state of the local buffering queues on the Raspberry Pi, the performance of the video processing pipeline (frame analysis and FPS), and operating system hardware metrics, including CPU temperature, CPU usage and RAM usage.

**Response payload:**
- device_id, datetime, connection_status, local_queues_state, processing_fps, cpu_temperature, cpu_usage, ram_usage

**Indexing requirements (DynamoDB optimisation):**
- (device_statuses) Reading the status history and writing telemetry is done with a composite key: PK - device_id (Partition Key) and SK - datetime (Sort Key).

---

## View 6: Alert management panel

**Functional description:**
- A system alert management centre allowing full handling (adding, removing and modifying) of entries on the blacklist of wanted vehicles.
- The screen shows the complete list of defined rules, sortable by the alert creation date and by the time it was last triggered in the field.
- Clicking a selected alert immediately loads and shows the full history of all detections so far related to that car.

**Response payload:**
- Alert configuration data: account_id, plate, created_at, alert_text, last_detected_at
- Related detection records (ANPR): account_id, device_id, plate, datetime, coordinates (GPS), s3_key, alert_id

**Indexing requirements (PostgreSQL / PostGIS optimisation):**
- For configuration data (alerts): search and sorting optimised by the indexes B-Tree (account_id), B-Tree (plate), B-Tree (created_at) and B-Tree (last_detected_at).
- For related detections (detections): searching the history related to a specific alert optimised by the index B-Tree (alert_id).

---

## Deviations

Proposed deviations of the implementation from the diagram. Status: `proposed` (waiting for team approval) / `agreed`.
In the OpenAPI contracts they are referenced as `D1`–`D24` (without the `#` sign, which starts a comment in YAML).

| No. | Diagram | Implementation | Justification | Status |
|---|---|---|---|---|
| D1 | Separate B-Tree on `account_id` and `datetime` | Composite indexes, e.g. `(account_id, datetime DESC)`, `(account_id, plate, datetime DESC)` | Every query filters by account and time at once; one composite index serves both conditions | proposed |
| D2 | Coordinates as `GEOMETRY` | `GEOGRAPHY(Point, 4326)` | `ST_DWithin` on geography measures the radius in metres (View 2); on geometry 4326 it uses degrees | proposed |
| D3 | `account_id` in every response | No `account_id` in API responses | The account comes from the token; the field adds nothing for the frontend. It is never an input parameter | proposed |
| D4 | `s3_key` in the response | `imageUrl` (presigned GET, short expiry) | The bucket is private; the browser cannot show a photo from the key alone | proposed |
| D5 | Autocomplete in `GET /views/anpr-search` | Separate `GET /detections/plate-suggestions` | A different, lighter response queried on every keystroke | proposed |
| D6 | No `GET /alerts/{id}` | Endpoint added | Edit form and refresh after 409 | proposed |
| D7 | `alerts` without id and version | `alert_id` (UUID), `version` | Endpoints use `{alert_id}`; `version` protects against overwriting a concurrent edit (409) | proposed |
| D8 | `detections` without a detection id | `detection_id` (UUID assigned by the RPi) | Idempotent SQS consumer: a duplicate message does not create a second record | proposed |
| D9 | Response fields as in "Response payload" | Additional fields and rules: `alertId` in detections of all views; `deviceId` in routes; `center`, `radiusMeters`, `truncated` (View 2, separately for detections and for the route); `ocrConfidence`, `detectorConfidence` from ingest; `nextCursor`, `hasMore`, `lastSeenAt`, `lastPosition` (View 3); `lastDetectedAt` in suggestions; one alert per plate within an account (409 `ALERT_ALREADY_EXISTS`) | Fields are only added (backward compatible); they make drawing the map and incremental polling easier for the frontend; alert uniqueness prevents duplicates on the blacklist | proposed |
| D10 | No pagination rules for the map and the RPi | No pagination, but with a limit: View 2, max 5000 detections (the most recent) + `truncated` flag, a route with at most one point per `trackIntervalSeconds` (request parameter, max 180 s) and at most 5000 points (the most recent) + `truncated` flag, time range max 7 days, radius max 5 km; alert list for the RPi, full list | The map and the device need the complete data at once; the limit protects the database from queries over months of data. Exception to the "size max 100" rule | agreed |
| D11 | Paths `/api/v1/views/...` | `/api/v1/detections/search`, `/plate-suggestions`, `/radial-analysis`, `/live-feed` | The path names a resource, not a screen of the frontend | agreed |
| D12 | "Photo gallery" tab in View 1 | Dropped from the plans: the results are a map and a list | Smaller scope | agreed |
| D13 | Partial plate search in View 1 | Optional `plate` as an exact match (partial numbers are served by `plate-suggestions`); `from` and `to` optional, an omitted side of the range is unbounded; `size` max 1000 instead of a separate endpoint for the map | A prefix could not find exactly `WA1234` without `WA12345`; the map uses the results of the same endpoint | agreed |
| D14 | `alert_id` in `detections`, `GET /alerts/{alert_id}/detections` | No column and no endpoint: the history of an alert is `GET /detections/search?plate=...`, and `alertId` in responses follows from the pair account and plate | The history is about the car, so it also covers detections from before the alert was created; deleting an alert breaks nothing | agreed |
| D15 | `GET /devices/{device_id}/alerts` | Removed: the RPi uses `GET /alerts` and gets the full list of its owner with an `ETag`; a person gets pages without an `ETag` | Alerts belong to the account, so all devices of an account have the same list | agreed |
| D16 | Modifying an alert | `PUT` changes `alertText` only, the plate is immutable (a fix is a delete and a new alert) | An alert is identified by its plate, and editing the plate had no defined meaning | agreed |
| D17 | `last_detection_time` stored in `alerts` | `lastDetectedAt` computed when reading: the latest `detectedAt` of the plate in the account (index `(account_id, plate, detected_at DESC)`) | Always consistent with the detections, also those delivered late (store-and-forward); consumers never modify alerts, so they do not bump their `version` | agreed |
| D18 | No way to get a single detection | Added `GET /detections/{detectionId}` | Details of a detection opened from a list or a map | agreed |
| D19 | Views 4 and 5 addressed by `device_id` | No device id in the paths: `GET /api/v1/device`, `/api/v1/device/config`, `/api/v1/device/metrics` (device-management-api.yaml). A device acts on itself, a person on the device of their account | The id comes from the token and cannot be forged; one device per account for now | agreed |
| D20 | View 4 payload: `device_id`, `plate_cooldown`, `batching_parameters`, `ML_model_parameters` | Adds `intervals` (metrics, configuration and alert polling, GPS sampling) and `camera` (exposure, gain, white balance, fps; the resolution is fixed at 4056x3040), plus `version` and `updatedAt`: a stale `version` is 409, and the device polls with `ETag` / `If-None-Match` | The device is configured remotely in full; optimistic locking as for alerts | agreed |
| D21 | View 5: `connection_status` stored with every status | `online` and `lastMetricsAt` computed in `GET /api/v1/device` from the latest measurement and the metrics interval of the device; measurements add free disk, uptime and the GPS state; kept for 7 days (TTL) | A device that stopped reporting cannot report that it is offline | agreed |
| D22 | `device_statuses` with SK `datetime` | Table `device-metrics` with SK `recordedAt`, epoch milliseconds of the measurement, the same name as in the API | A number sorts chronologically; the table is named after what it holds | agreed |
| D23 | No device registry | Table `devices` (PK `deviceId`, index by `accountId`) with the owner, the Cognito username and the ownership version; administrator endpoints create and delete devices (docs/device-management.md) | The source of truth of ownership and of the device events | agreed |
| D24 | View 6: alert list without filters | Optional filters in `GET /alerts` for people: plate prefix and creation time range (`from` inclusive, `to` exclusive); `to` must be after `from` (400 `INVALID_TIME_RANGE`) | With pagination a client-side filter only searches the current page; finding one alert on a long blacklist needs a server-side filter | proposed |

---

## Open questions (to be agreed within the team)

1. Who approves deviations D1–D24? Until approval the contract is a draft version (`0.x`).
2. Expiry of the photo presigned URLs (D4): cached pages stop working once they expire.
3. Limit not in the diagram: Live Feed window max 60 min. Do we accept it?

---

## Known limitations

1. **View 3, Live Feed cursor.** The cursor follows the order in which detections were stored (ingestion time, then `detectionId`), so detections of one batch with an identical ingestion time are not lost. Two batches stored at the same time can finish their transactions in a different order than they started, so the Live Feed returns only detections stored at least 2 seconds before the request. This holds as long as the consumer transaction that stores a batch takes less than 2 seconds; a longer one can be skipped by the cursor. Cost: new detections appear in the Live Feed about 2 seconds later. Clients need no deduplication.
