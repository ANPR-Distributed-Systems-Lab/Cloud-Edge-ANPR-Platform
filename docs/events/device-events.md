# Device events

Events about the link between a device and its owner. device-management publishes them when it pairs,
reassigns or unpairs a device; every service that needs the link keeps its own copy built from them
(today: operations). The background is in [identity-and-access.md](../identity-and-access.md).

Status: design agreed, not implemented yet.

## 1. Flow

```
device-management --publish (after the DynamoDB write)--> SNS topic "device-events"
                                                               |
                                      SQS queue "operations-device-events" (+ DLQ) --> consumer in operations
```

- One topic, owned by device-management, which is the only publisher.
- One queue per consuming service, each with its own DLQ (5 receives, then the message moves to the DLQ,
  retention set to the maximum of 14 days). The subscription uses raw message delivery, so the consumer
  reads the body and the message attributes directly.
- A new consumer is a new queue subscribed to the topic. The publisher does not change.
- The topic is separate from `edge-events` on purpose: these events decide which user owns which data, so
  only the task role of device-management may publish here, while the devices' Lambda publishes there.
- Locally nothing connects to these topics and queues on AWS (see `CLAUDE.md`, section 4).

## 2. Events

| `eventType` | Published when |
|---|---|
| `device.paired` | A device gets an owner, the first time or when the owner changes |
| `device.unpaired` | A device loses its owner |

### Message attributes

| Attribute | Notes |
|---|---|
| `eventType` | `device.paired` or `device.unpaired`; subscriptions can filter on it |
| `traceId` | Trace id of the pairing request, copied into the logs of every consumer |

### Body

```json
{
  "eventId": "0192f3a4-7c1e-7b2a-9d41-5f3e8a1c2b10",
  "occurredAt": "2026-11-01T10:00:00.000Z",
  "version": 1,
  "deviceId": "7d3f2c1e-0000-4000-8000-000000000000",
  "accountId": "d1c2a0f8-0000-4000-8000-000000000000"
}
```

| Field | Required | Meaning |
|---|---|---|
| `eventId` | yes | UUID of the event, for logs and tracing |
| `occurredAt` | yes | RFC 3339 UTC time of the change |
| `version` | yes | Integer per device, starting at 1 and raised by device-management on every ownership change. Stored in the device item |
| `deviceId` | yes | Cognito `sub` of the device account |
| `accountId` | `device.paired` only | The owning user account. Absent in `device.unpaired` |

There is no schema version field for now. Changes are additive only: new fields may appear, existing ones
keep their meaning.

## 3. What a consumer does

- Delivery is at-least-once and unordered, so processing is idempotent and uses `version`: the event is
  applied only if its `version` is higher than the stored one for that `deviceId` (or nothing is stored).
  Equal or lower versions are acknowledged and ignored.
- `device.paired`: upsert the account `accountId` (when missing) and the link `deviceId` → `accountId`
  together with `version`, in one transaction.
- `device.unpaired`: remove the link (or mark it inactive, the service decides), keep `version`. Records
  stored earlier keep the owner they had.
- The message is deleted from the queue only after the transaction commits. On failure it returns after the
  visibility timeout, and after 5 failed receives it goes to the DLQ. One bad message must not block the queue.

## 4. Interaction with edge events

Detections and device locations travel on another topic and queue, so nothing orders them against pairing
events. When operations receives a detection of a device it has no link for, it fails the message. The
message returns after the visibility timeout (60 s) and succeeds as soon as the pairing event is processed.
If that does not happen within 5 receives, the message lands in the DLQ and can be redriven after the cause is
fixed. The same happens to data of a device that was unpaired but still holds a valid token.

## 5. Open points

- **Publish failure after the write.** If the DynamoDB write succeeds and the publish fails, consumers never
  learn about the change. Postponed on purpose, see [identity-and-access.md](../identity-and-access.md#10-open-points)
  for the candidates (idempotent endpoint that republishes, republish-all action, DynamoDB Streams).
- **Rebuilding a consumer.** A new or restored database has no way to replay events. A "republish all pairs"
  action is the likely answer.
- **Unpairing semantics.** Whether the Cognito user of the device is disabled at the same time.
- **Alarm on the DLQ.** An alarm on the depth of the DLQ is planned together with the Terraform change.
- **Several devices per account.** The events already carry one device each, so they do not change.
