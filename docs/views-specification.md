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
In the OpenAPI contract they are referenced as `D1`–`D10` (without the `#` sign, which starts a comment in YAML).

| No. | Diagram | Implementation | Justification | Status |
|---|---|---|---|---|
| D1 | Separate B-Tree on `account_id` and `datetime` | Composite indexes, e.g. `(account_id, datetime DESC)`, `(account_id, plate, datetime DESC)` | Every query filters by account and time at once; one composite index serves both conditions | proposed |
| D2 | Coordinates as `GEOMETRY` | `GEOGRAPHY(Point, 4326)` | `ST_DWithin` on geography measures the radius in metres (View 2); on geometry 4326 it uses degrees | proposed |
| D3 | `account_id` in every response | No `account_id` in API responses | The account comes from the token; the field adds nothing for the frontend. It is never an input parameter | proposed |
| D4 | `s3_key` in the response | `imageUrl` (presigned GET, short expiry) | The bucket is private; the browser cannot show a photo from the key alone (Gallery, View 1) | proposed |
| D5 | Autocomplete in `GET /views/anpr-search` | Separate `GET /views/anpr-search/plate-suggestions` | A different, lighter response queried on every keystroke | proposed |
| D6 | No `GET /alerts/{id}` | Endpoint added | Edit form and refresh after 409 | proposed |
| D7 | `alerts` without id and version | `alert_id` (UUID), `version` | Endpoints use `{alert_id}`; `version` protects against overwriting a concurrent edit (409) | proposed |
| D8 | `detections` without a detection id | `detection_id` (UUID assigned by the RPi) | Idempotent SQS consumer: a duplicate message does not create a second record | proposed |
| D9 | Response fields as in "Response payload" | Additional fields and rules: `alertId` in detections of all views; `deviceId` in routes (derived from `accounts`, because `device_locations` does not have it); `center`, `radiusMeters`, `truncated` (View 2); `generatedAt`, `lastSeenAt`, `lastPosition` (View 3); `lastDetectedAt` in suggestions; one alert per plate within an account (409 `ALERT_ALREADY_EXISTS`) | Fields are only added (backward compatible); they make drawing the map and incremental polling easier for the frontend; alert uniqueness prevents duplicates on the blacklist | proposed |
| D10 | No pagination rules for the map and the RPi | No pagination, but with a limit: View 2, max 1000 detections + `truncated` flag, time range max 7 days; alert list for the RPi, full list | The map and the device need the complete data at once; the limit protects the database from queries over months of data. Exception to the "size max 100" rule | proposed |

---

## Open questions (to be agreed within the team)

1. Who approves deviations D1–D10? Until approval the contract is a draft version (`0.x`).
2. View 6: history of detections "related to that car": only detections assigned to the alert (`alert_id`, as in the diagram: endpoint and index), or all detections of that plate, including those from before the alert was created?
3. View 1: map pins: only the current results page (max 100), or a separate response with all points / clusters?
4. Alert list for the RPi: does the device need anything besides the plate (e.g. `alertText`)?
5. How does the RPi obtain a JWT: a Cognito user token or a separate device identity?
6. Expiry of the photo presigned URLs (D4): the gallery and cached pages stop working once they expire.
7. Changing the plate of an existing alert: what happens to detections already assigned to it? Deleting an alert: is `alert_id` in detections set to `null`?
8. Limits not in the diagram: radius 25–5000 m, Live Feed window max 60 min, View 2 time range max 7 days. Do we accept them?
