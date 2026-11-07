# POST /api/v1/ingest/detections

Edge-to-cloud ingestion of ANPR detections. The Raspberry Pi sends a batch of detections; API Gateway
authenticates the request and hands it to a Lambda, which validates the whole batch and publishes it to SNS.
Nothing is written to a database on this path, the consuming services (e.g. operations-service) read the
event from their own SQS queues.

Status: design draft. The OpenAPI contract will be written from this document. Section 8 lists what the
bootstrap Lambda already does and what is still to be built.

## 1. Flow

```
RPi --POST--> API Gateway (JWT authorizer "devices") --> Lambda (validate, publish) --> SNS topic "edge-events"
                                                                                           |
                                                                      fan-out (SQS queue per service, each with a DLQ)
```

- The caller is a device account (see [identity-and-access.md](../identity-and-access.md)). The Lambda takes
  the `deviceId` from the validated token (`sub`) and requires `account_type = device`. Nothing about identity
  is read from the body.
- The owner of the device is **not** in the token or the event. Each consumer resolves it from its own pairing
  table.
- The request is validated atomically: if any detection is invalid, nothing is published and the whole batch
  is rejected (see section 4). The gateway is an HTTP API, which has no request models, so the Lambda
  validates everything.
- One request produces exactly one SNS message (a single `Publish`), so the publish step is atomic too. The
  validated body is forwarded unchanged and the routing data travels in message attributes.

## 2. Request

### Headers

| Header | Required | Notes |
|---|---|---|
| `Authorization: Bearer <access token>` | yes | Access token of the `device` app client, validated by API Gateway |
| `Content-Type: application/json` | yes | Anything else returns 415 |
| `X-Trace-Id` | no | 1 to 64 characters from `A-Z a-z 0-9 -`. Otherwise the API Gateway request id is used. Always echoed in the response header `X-Trace-Id` and as `traceId` |

### Body

```json
{
  "batchId": "0192f3a4-7c1e-7b2a-9d41-5f3e8a1c2b10",
  "detections": [
    {
      "detectionId": "0192f3a4-7c1f-7e11-8a02-6b7d4c9e1a01",
      "frameId": "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c",
      "detectedAt": "2026-10-30T09:14:22.381Z",
      "plate": "WA12345",
      "ocrConfidence": 0.94,
      "detectorConfidence": 0.88,
      "imageKey": "images/7d3f2c1e-0000-4000-8000-000000000000/2026/10/30/0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c.jpg",
      "corners": [[0.412, 0.531], [0.447, 0.529], [0.448, 0.548], [0.413, 0.551]],
      "location": { "lat": 52.229676, "lon": 21.012229, "accuracyM": 4.5, "fixAgeMs": 300 }
    }
  ]
}
```

A frame with several plates is several detections that share `frameId` and `imageKey`.

### Fields

| Field | Required | Type and rules |
|---|---|---|
| `batchId` | yes | UUID. Identifies the request in logs; resending the same batch reuses it |
| `detections` | yes | Array, 1 to 100 items |
| `detections[].detectionId` | yes | UUID (v7 recommended), generated on the RPi. Idempotency key and Trace ID of this detection. Unique within the batch |
| `detections[].frameId` | yes | UUID of the analysed frame. Detections of the same frame share it |
| `detections[].detectedAt` | yes | RFC 3339 UTC with `Z`, millisecond precision. Moment the frame was captured |
| `detections[].plate` | yes | `^[A-Z0-9]{3,8}$`: uppercase letters and digits, no spaces (same convention as the labeling guide) |
| `detections[].ocrConfidence` | yes | Number, 0 to 1 inclusive |
| `detections[].detectorConfidence` | yes | Number, 0 to 1 inclusive |
| `detections[].imageKey` | yes | S3 object key (never a URL, presigned URLs expire and carry a signature): `images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg`, where `deviceId` is the calling device and `frameId` the frame of this detection. Assigned by device-management together with the presigned upload URL (`POST /api/v1/images/presigned-urls`), never built by the device |
| `detections[].corners` | yes | 4 points `[x, y]`, normalized to 0-1 on the image referenced by `imageKey`, order top-left, top-right, bottom-right, bottom-left (clockwise, convex, non-degenerate) |
| `detections[].location` | yes | Object, see below |
| `location.lat` | yes | Number, -90 to 90, WGS84 decimal degrees |
| `location.lon` | yes | Number, -180 to 180, WGS84 decimal degrees |
| `location.accuracyM` | no | Number, 0 or more. Horizontal accuracy estimate |
| `location.fixAgeMs` | no | Integer, 0 or more. Age of the GPS fix when the frame was captured |

Additional rules:
- `location` is always required. The edge decides what to do without a GPS fix (wait or use the last
  known position and report its age in `fixAgeMs`).
- `lat = 0` together with `lon = 0` is rejected (typical "no fix" value).
- `detectedAt` may not be in the future by more than 5 minutes (proposed default), and not older than
  30 days (proposed default, store-and-forward can deliver old data after a long outage).
- Unknown properties are ignored by the validation, but are not removed from the forwarded body.
- The request body is limited to 250 KiB (SNS accepts 256 KiB per message including attributes). 100
  detections are about 60 KB.

## 3. Success response

`202 Accepted`

```json
{ "batchId": "0192f3a4-7c1e-7b2a-9d41-5f3e8a1c2b10", "accepted": 1, "traceId": "5b0f6c6e-0c9a-4d57-9f3a-2f3d8b8e7c11" }
```

`accepted` always equals the number of detections in the request (the request is atomic). A detection whose
`detectionId` was already received earlier is not an error: the downstream consumers deduplicate on it.
`202` means the batch is on the topic, not that a consumer has processed it.

## 4. Error responses

Errors produced by our Lambda are RFC 9457 problem documents (`application/problem+json`), the same shape
the Spring services use, with the stable `code` and the `requestId` (= the trace id). Validation errors add
`fields[]`, which lists **all** problems found, not only the first:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "detail": "2 validation errors, nothing was accepted",
  "code": "VALIDATION_FAILED",
  "requestId": "5b0f6c6e-0c9a-4d57-9f3a-2f3d8b8e7c11",
  "fields": [
    { "index": 0, "field": "detections[0].plate", "code": "PATTERN", "message": "must match ^[A-Z0-9]{3,8}$" },
    { "index": 3, "field": "detections[3].corners", "code": "INVALID_CORNERS", "message": "corners must be clockwise and convex" }
  ]
}
```

`index` is the position of the offending detection in the batch (absent for errors about the batch itself).

| HTTP | `code` | Produced by | When |
|---|---|---|---|
| 400 | `INVALID_JSON` | Lambda | The body is not a UTF-8 JSON object |
| 400 | `VALIDATION_FAILED` | Lambda | Any rule in section 2 is broken. Nothing is published |
| 401 | (gateway) | API Gateway | Missing, invalid or expired token, or a token of another app client |
| 403 | `FORBIDDEN` | Lambda | Valid token, but it is not a device token (no `sub` or `account_type` is not `device`) |
| 413 | `PAYLOAD_TOO_LARGE` | Lambda (API Gateway above 10 MB) | Body over the size limit |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Lambda | `Content-Type` is not `application/json` |
| 429 | (gateway) | API Gateway | Throttled. Honour `Retry-After` |
| 500 | `INTERNAL_ERROR` | Lambda | Unexpected failure. Nothing was published |
| 503 | `PUBLISH_FAILED` | Lambda | The SNS publish failed. Nothing was accepted |
| 504 | (gateway) | API Gateway | Lambda timeout. It is unknown whether the publish happened |

`fields[].code` values: `REQUIRED`, `TYPE`, `FORMAT` (UUID, timestamp), `PATTERN`, `RANGE`, `SIZE` (array
length), `INVALID_CORNERS`, `INVALID_LOCATION`, `DUPLICATE_DETECTION_ID` (twice in one batch),
`TIMESTAMP_IN_FUTURE`, `TIMESTAMP_TOO_OLD`, `IMAGE_KEY_FOREIGN` (an `imageKey` under the prefix of another
device; a body error, so 400 like the others, while 403 is kept for the token).

Errors produced by the HTTP API itself (401, 429, 504) have the gateway's default body, which cannot be
customised on an HTTP API. The edge relies on the status code for them, not on the body.

### What the edge does with each outcome

| Outcome | Edge behaviour |
|---|---|
| 202 | Delete the batch from the local queue |
| 400, 413, 415 | The same body will never succeed: do not retry it. Move it to a local quarantine and log it. Because validation is atomic, one bad detection rejects up to 99 good ones, so the edge should validate with the same rules before sending and, on a 400, may split the batch and resend the valid part |
| 401 | Refresh the token and retry |
| 403 | Configuration problem (not a device token): stop retrying and raise the alert beep |
| 429, 5xx, network error | Retry with exponential backoff and jitter, with the **same** `batchId` and `detectionId`s (safe, the pipeline is idempotent) |

## 5. SNS event

The Lambda publishes the validated body **unchanged**, as the message, with these message attributes:

| Attribute | Value |
|---|---|
| `eventType` | `detection`, derived from the route and never taken from the client |
| `traceId` | The trace id of the request |
| `deviceId` | The `sub` of the device token |

There is no owner in the event. Consumers resolve it from their pairing table (see
[device-events.md](../events/device-events.md)). Subscriptions use raw message delivery, so a consumer reads
the body and the attributes directly, and can filter on `eventType`.

Each consumer reads the batch, deduplicates by `detectionId` and stores what it needs. The Trace ID of an
individual detection is its `detectionId`; `traceId` identifies the request. All logs are JSON and contain
these ids (project convention). Request bodies are never logged: they contain plates and GPS positions.

## 6. Unpaired devices

Ingest does not check whether the device has an owner (that would need a call to the device registry on every
request). A token of an unpaired device is accepted with `202`. The consumer cannot resolve the owner, the
message is retried and, after the retries, moves to the DLQ. See
[device-events.md](../events/device-events.md#4-interaction-with-edge-events).

## 7. Image upload ordering

The image may be uploaded to S3 after the detection arrives (separate local queues on the edge), so the
UI must tolerate a missing object for a short time.

## 8. Implementation status

The Lambda lives in `infrastructure/lambdas/event_ingest` and implements this document and
[ingest-device-locations.md](ingest-device-locations.md): identity, content type, size, the atomic validation
with `fields[]` and the `202` body. Unit tests next to it cover every rule.

operations-service consumes both event types from its queue (`messaging/edge`) and stores them in `detections`
and `device_locations` with the owner resolved from its `devices` table. A batch is stored in one transaction,
deduplicated by `detectionId` / `locationId`. Tested locally, not deployed.

## 9. Open points

- Proposed defaults to confirm: max 100 detections, 250 KiB body, 5-minute future and 30-day past limits for
  `detectedAt`, `accuracyM` and `fixAgeMs` optional, unknown properties ignored.
- `POST /api/v1/ingest/device-locations` is specified separately.
