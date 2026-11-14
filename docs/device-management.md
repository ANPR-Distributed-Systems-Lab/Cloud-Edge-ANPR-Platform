# device-management-service

Control plane of the edge fleet: the registry of devices and their owners, the configuration of each device
(View 4), its health metrics (View 5), the presigned URLs the devices upload their photos with and the presigned
URLs they download their models with. It owns three DynamoDB tables and is the only publisher of the device
events.

Status: implemented on the branch `feature/device-management-service-bootstrap`, with unit tests and integration
tests against DynamoDB Local. Its infrastructure (tables, routes, permissions) is applied on `dev`; the service
itself is not deployed yet. The contract is
[`device-management-service/device-management-api.yaml`](../device-management-service/device-management-api.yaml),
and identities are described in [identity-and-access.md](identity-and-access.md).

## 1. Endpoints

The device is never named in a path. A device acts on itself and a person on the device of their account,
found through the index of the registry (one device per account for now). API Gateway lets in only the kind of
token a route is for (`infrastructure/envs/dev/api.tf`), and the service checks the caller type again.

| Endpoint | Caller | Purpose |
|---|---|---|
| `GET /api/v1/device` | person, device | The device with `lastMetricsAt` and `online` |
| `GET /api/v1/device/config` | person, device | Configuration with `ETag`; the device polls with `If-None-Match` and gets `304` when nothing changed |
| `PUT /api/v1/device/config` | person | Replaces the whole configuration; `version` from the last read, `409 CONCURRENT_MODIFICATION` when stale |
| `POST /api/v1/device/metrics` | device | 1 to 100 measurements, validated as a whole; `204` |
| `GET /api/v1/device/metrics` | person | The `limit` (up to 1000) most recent measurements of the last 7 days, optionally before `before`, oldest first |
| `POST /api/v1/images/presigned-urls` | device | 1 to 100 frames; the PUT URL, valid for 30 minutes, of the key `images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg` of each (the device computes the same key and sends its detection before the upload) |
| `GET /api/v1/device/models` | device | The model versions of its configuration; per file the SHA-256, the size and a GET URL valid for 30 minutes; `409 MODEL_NOT_PUBLISHED` for a version that is not published (section 3) |
| `POST /api/v1/admin/devices` | administrator (SigV4) | Creates a device for a person |
| `DELETE /api/v1/admin/devices/{deviceId}` | administrator (SigV4) | Deletes a device |

Errors are RFC 9457 problems with `code` and `requestId`, the same shape as operations-service and the ingest
Lambda. Validation errors list every problem in `fields[]`; `index` is the position of the item in a batch. The
field codes are shared by every service and the ingest Lambda (`REQUIRED`, `RANGE`, `SIZE`, `PATTERN`), plus
`TIMESTAMP_IN_FUTURE`, `TIMESTAMP_TOO_OLD`, `DUPLICATE_RECORDED_AT`, `PASSWORD_POLICY` and `MODEL_NOT_PUBLISHED`
here.

## 2. Data (DynamoDB)

| Table | Keys | Item |
|---|---|---|
| `devices` | PK `deviceId`; index `accountId-index` (PK `accountId`) | `accountId` (owner), `username` (Cognito login), `createdAt`, `version` (ownership version, sent in the device events) |
| `device-configurations` | PK `deviceId` | `version` (optimistic locking, raised on every write), `updatedAt` and the settings as top-level attributes: `plateCooldownSeconds`, `batching`, `ml`, `models`, `intervals`, `camera` |
| `device-metrics` | PK `deviceId`, SK `recordedAt` (epoch ms of the measurement) | The metrics of one measurement and `expiresAt` (epoch seconds, table TTL) |

- A device and its configuration are written and deleted together in one transaction, so a registered device
  always has a configuration.
- Measurements are keyed by the moment they were recorded, so a resent batch overwrites itself
  (store-and-forward is idempotent). They are refused when older than the retention (7 days) and expire after
  it. DynamoDB deletes expired items with a delay, so reads also filter on the retention.
- The item classes are the domain objects (mutable JavaBeans, as the DynamoDB mapper requires), and
  `DynamoDbTablesIT` pins their key schemas to those of Terraform.

## 3. Configuration

- The configuration is the only source of the device's settings (decided 2026-11-12): the send rule
  thresholds (`ml`: detector and OCR confidence, P(readable), plate width, edge margin), the model versions
  (`models`), the cooldown, batching, intervals and the camera, including the flips of how it is mounted. The
  device keeps a copy and has no defaults of its own (`rpi-edge/DETECTION.md`, section 4).
- A new device starts with the defaults of the service (`app.configuration.defaults` in `application.yaml`):
  the ML starting points of `ml-models/ML_ASSUMPTIONS.md` (0.40 / 0.80 / 0.80 / 70 px / 10 px, still open there),
  the published models v2 / v3 and the camera settings tested on the Pi. They must satisfy the ranges of the
  contract, which `DefaultSettingsIT` checks. Enum values are uppercase in the API (`MANUAL`, `DAYLIGHT`).
- `models.detector` and `models.ocr` must name published versions: a `PUT` naming another one is
  `400 VALIDATION_FAILED` with the field code `MODEL_NOT_PUBLISHED`. A version is published when
  `models/{model}/{version}/release.json` exists in the models bucket (`infrastructure/envs/dev/models.tf`,
  written by `anpr-publish-model` of ml-models); it lists the files of the version with their SHA-256 and size.
  `GET /api/v1/device/models` reads it for the versions of the device's configuration and signs a GET URL per
  file (`internal/models`). The device downloads them, checks the SHA-256 and switches without a restart. The
  defaults are not checked at startup: until v2 and v3 are published, a new device's `GET /api/v1/device/models`
  answers `409 MODEL_NOT_PUBLISHED`.
- The resolution is fixed at 4056x3040, so `camera.fps` is at most 11.7.
- `ETag` is the quoted version (`"3"`) and `If-None-Match` is compared weakly (RFC 9110).

## 4. Online state

A device is online while its latest measurement is younger than `N` metrics intervals of the device
(`intervals.metricsSeconds` of its configuration). `N` is `app.overview.online-within-metrics-intervals`
(3 by default). A device that never reported, or not within the retention, is offline with
`lastMetricsAt = null`.

## 5. Creating and deleting a device

A device spans three systems: its Cognito user, its records in DynamoDB and the copies the consumers of the
device events keep. There is no transaction across them, so each operation orders its steps to stay
consistent when one fails.

**Create** (`POST /api/v1/admin/devices` with `accountId`, `username`, `password`):

1. The account must be a person: a Cognito user found by `sub` and in the group `users`, otherwise
   `404 ACCOUNT_NOT_FOUND`. It must have no device yet, otherwise `409 ACCOUNT_HAS_DEVICE`.
2. Create the Cognito user (no message sent), set the permanent password and add the user to the group `devices`.
   A taken username is `409 USERNAME_TAKEN`. A password the pool refuses is `400 VALIDATION_FAILED` with the
   field code `PASSWORD_POLICY`, and the half-created user is deleted.
3. Write the device item (`version = 1`) and its default configuration in one transaction.
4. Publish `device.paired`.

If step 3 or 4 fails, the earlier steps are undone (records removed, Cognito user deleted) and the request answers
500, so it can simply be repeated. An undo step that fails is logged at ERROR with what is left behind.

**Delete** (`DELETE /api/v1/admin/devices/{deviceId}`):

1. Delete the Cognito user. The device can no longer sign in or refresh its tokens.
2. Publish `device.unpaired` with `version + 1`.
3. Delete the device item and its configuration in one transaction.

Every step is idempotent and the registration is removed last, so repeating a failed deletion finishes it. Until
an access token the device already holds expires, the ingest Lambda still accepts it, and those events end in the
DLQ of the consumers. This service refuses the token as soon as the registration is gone. Measurements expire
by themselves, and detections stay with the account they belonged to.

## 6. Logs and tracing

- Logs are JSON (Elastic Common Schema); only the profile `local` logs plain text (section 9). Every line of a
  request carries `traceId`: the client's `X-Trace-Id` (1 to 64 characters from `A-Z a-z 0-9 -`), otherwise the
  request id of API Gateway (`X-Request-Id`, the id in its access logs), otherwise a generated one. This is the
  rule of the ingest Lambda and of operations-service too. The trace id is returned in the `X-Trace-Id` header and
  as `requestId` of errors, and the device events carry it as the attribute `traceId`.
- Passwords are never logged or returned. Ids (device, account, event) are logged as fields.

## 7. Code layout

```
com.anpr.devicemanagement
├── api/<area>/           controllers implementing the generated interfaces, MapStruct mappers, error handler
├── internal/<area>/      domain and DynamoDB repositories: devices, configuration, metrics, images, overview,
│                         provisioning (create/delete and the ports AccountDirectory and DeviceEvents)
├── identity/             Cognito adapter of AccountDirectory
├── messaging/            SNS adapter of DeviceEvents
├── storage/              S3 adapter of ModelReleases (the release descriptions of the models)
├── config/               AWS clients and properties
├── local/                profile local: table creation and stand-ins for Cognito, SNS and the models bucket (section 9)
└── shared/               errors, caller identity, trace id, timestamp window
```

`internal/` never imports from `api/`, `identity/`, `messaging/`, `storage/` or `local/`: the internal areas define
the ports, and the adapters implement them.

## 8. Known limitations

- **One device per account** is checked through an eventually consistent index, so two creations for one account
  within about a second could both pass. Creation is a rare administrator action.
- **Publish after a timeout.** If SNS accepted `device.paired` but the call timed out, the creation is undone
  while the consumers keep the pairing of a device that no longer exists (and cannot sign in).
- **Presigned PUT** cannot limit the size of the upload. A presigned POST with a `content-length-range` policy
  could.
- **Presigned URL lifetime** is also bounded by the temporary credentials of the task role that signed it.

## 9. Local development

Run the application from the IDE with the profile `local` (`SPRING_PROFILES_ACTIVE=local`):

- Spring Boot starts `device-management-service/compose.yaml` (DynamoDB Local on `localhost:8000`, data kept in a
  Docker volume) and the application creates the missing tables, with the same keys and index as Terraform.
- Cognito and SNS are replaced by stand-ins: every account id counts as a person, device accounts are kept in
  memory, and device events are logged instead of published (CLAUDE.md, section 4).
- Upload and download URLs are signed with dummy credentials: they have the right form, but there is no local S3
  behind them. Every model version counts as published, with zero checksums; to run a device without AWS, use
  `rpi-edge/tools/dev_cloud.py` instead.
- The profile refuses to start without a local DynamoDB endpoint, so the stand-ins can never run in AWS.

There is no API Gateway locally, so requests carry the identity headers it would inject:

```bash
# Create a device (administrator); the response holds the deviceId
curl -X POST localhost:8080/api/v1/admin/devices -H "X-Account-Type: iam" -H "X-Account-Id: local-admin" \
  -H "Content-Type: application/json" \
  -d '{"accountId": "d1c2a0f8-0000-4000-8000-000000000000", "username": "rpi-01", "password": "Local-password-1"}'

# Read the configuration as its owner (a person) or as the device itself
curl localhost:8080/api/v1/device/config -H "X-Account-Type: user" -H "X-Account-Id: d1c2a0f8-0000-4000-8000-000000000000"
curl localhost:8080/api/v1/device/config -H "X-Account-Type: device" -H "X-Account-Id: <deviceId>"
```

Device accounts live in memory, so after a restart the devices in DynamoDB Local remain while their usernames
are free again. `docker compose down -v` in the service directory starts from an empty database.
