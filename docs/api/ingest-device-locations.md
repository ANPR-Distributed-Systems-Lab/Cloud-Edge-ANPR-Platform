# POST /api/v1/ingest/device-locations

Edge-to-cloud ingestion of the device's GPS track. The Raspberry Pi sends a batch of position points;
API Gateway authenticates the request and hands it to a Lambda, which validates the whole batch and publishes
it to SNS. It works exactly like [`/api/v1/ingest/detections`](ingest-detections.md): same flow, same
headers, same error body and the same retry rules for the edge. This document lists the payload and what
differs.

Status: design draft. The OpenAPI contract will be written from these documents.

## 1. Flow

```
RPi --POST--> API Gateway (JWT authorizer "devices") --> Lambda (validate, publish) --> SNS topic "edge-events"
                                                                                           |
                                                                      fan-out (SQS queue per service, each with a DLQ)
```

- The device identity comes from the validated token (`sub` = `deviceId`, `account_type = device`), never
  from the body. The owner is resolved by each consumer from its pairing table, see
  [identity-and-access.md](../identity-and-access.md).
- The request is validated atomically: any invalid point rejects the whole batch and nothing is published.
- One request produces exactly one SNS message (a single `Publish`), the validated body unchanged.
- Detections and device locations share the topic `edge-events`; the message attribute `eventType`
  (`detection` or `device-location`) tells them apart, so subscriptions can filter on it.

## 2. Request

### Headers

Same as for detections: `Authorization: Bearer <access token>` (required), `Content-Type: application/json`
(required), `X-Trace-Id` (optional, echoed in the response).

### Body

```json
{
  "batchId": "0192f3a4-9a10-7c3b-8e55-2a4b6c8d0e12",
  "locations": [
    {
      "locationId": "0192f3a4-9a11-7d20-9c01-3b5d7f9a1c02",
      "recordedAt": "2026-10-30T09:14:21.000Z",
      "lat": 52.229676,
      "lon": 21.012229,
      "accuracyM": 4.5,
      "speedMps": 13.9,
      "headingDeg": 87.0
    },
    {
      "locationId": "0192f3a4-9a11-7d21-8b12-4c6e8a0b2d03",
      "recordedAt": "2026-10-30T09:14:22.000Z",
      "lat": 52.229681,
      "lon": 21.012431,
      "accuracyM": 4.4,
      "speedMps": 14.1,
      "headingDeg": 87.5
    }
  ]
}
```

### Fields

| Field | Required | Type and rules |
|---|---|---|
| `batchId` | yes | UUID. Identifies the request in logs; a resend reuses it |
| `locations` | yes | Array, 1 to 500 items. Points need not be sorted, consumers sort by `recordedAt` |
| `locations[].locationId` | yes | UUID (v7 recommended), generated on the RPi. Idempotency key. Unique within the batch |
| `locations[].recordedAt` | yes | RFC 3339 UTC with `Z`, millisecond precision. Time of the GPS fix |
| `locations[].lat` | yes | Number, -90 to 90, WGS84 decimal degrees (6 decimals is about 0.1 m) |
| `locations[].lon` | yes | Number, -180 to 180, WGS84 decimal degrees |
| `locations[].accuracyM` | no | Number, 0 or more. Horizontal accuracy estimate |
| `locations[].speedMps` | no | Number, 0 or more. Ground speed in metres per second |
| `locations[].headingDeg` | no | Number, 0 (inclusive) to 360 (exclusive). Course over ground, omit when stationary |

Additional rules:
- `lat = 0` together with `lon = 0` is rejected (typical "no fix" value). Without a fix the edge sends no point.
- `recordedAt` may not be in the future by more than 5 minutes (proposed default), and not older than
  30 days (proposed default, store-and-forward can deliver old data after a long outage).
- Unknown properties are ignored by the validation, but are not removed from the forwarded body.
- The request body is limited to 250 KiB (SNS accepts 256 KiB per message including attributes). 500 points
  are about 75 KB.
- Sampling is the edge's decision. Suggested: at most 1 point per second while moving, and fewer while
  stationary. After a long outage the edge sends the backlog in several batches of up to 500 points.

## 3. Success response

`202 Accepted`

```json
{ "batchId": "0192f3a4-9a10-7c3b-8e55-2a4b6c8d0e12", "accepted": 2, "traceId": "9c1e2f40-5a77-4b0d-8a31-6d2f0e9b7a55" }
```

`accepted` always equals the number of points in the request. A point whose `locationId` was already
received is not an error: the consumers deduplicate on it.

## 4. Error responses

The error document (RFC 9457 with `code`, `requestId` and `fields[]`), the 401/403/413/415/429/500/503/504
behaviour and the retry rules for the edge are identical to
[ingest-detections.md](ingest-detections.md#4-error-responses). `VALIDATION_FAILED` lists all problems found
in the batch, with the index of the offending point:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "detail": "1 validation error, nothing was accepted",
  "code": "VALIDATION_FAILED",
  "requestId": "9c1e2f40-5a77-4b0d-8a31-6d2f0e9b7a55",
  "fields": [
    { "index": 1, "field": "locations[1].lat", "code": "RANGE", "message": "must be between -90 and 90" }
  ]
}
```

`fields[].code` values for this endpoint: `REQUIRED`, `TYPE`, `FORMAT` (UUID, timestamp), `RANGE`, `SIZE`
(array length), `INVALID_LOCATION` (`0, 0`), `DUPLICATE_LOCATION_ID` (twice in one batch),
`TIMESTAMP_IN_FUTURE`, `TIMESTAMP_TOO_OLD`.

Because the validation is atomic, the edge should validate points with the same rules before sending, and
quarantine a batch that was rejected with 400 instead of retrying it.

## 5. SNS event

The Lambda publishes the validated body unchanged, with the message attributes `eventType`
(`device-location`), `traceId` and `deviceId` (the `sub` of the token). There is no owner in the event,
consumers resolve it from their pairing table. Subscriptions use raw message delivery.

Each consumer reads the batch, deduplicates by `locationId` and stores what it needs. Individual points
carry no Trace ID of their own (too many, too little business value): logs use the request-level `traceId`
and `batchId`. The consumer of operations-service is described in
[ingest-detections.md](ingest-detections.md#8-implementation-status).

Devices that have no owner yet behave as described in
[ingest-detections.md](ingest-detections.md#6-unpaired-devices).

## 6. Open points

- Proposed defaults to confirm: max 500 points, 250 KiB body, 5-minute future and 30-day past limits for
  `recordedAt`, `accuracyM`, `speedMps` and `headingDeg` optional, unknown properties ignored.
- Whether a point should also be accepted when `accuracyM` is very poor, or the edge filters those out before sending.
