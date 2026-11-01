# Identity and access

Who may call what, how a caller is identified, and how a device is linked to the user who owns it.

Status: design agreed, not implemented yet. The bootstrap Terraform in `infrastructure/` differs from this
document in the places listed in [section 9](#9-changes-to-the-bootstrap).

## 1. Principles

- Amazon Cognito establishes identity and API Gateway validates the token. Backends never take the identity
  of the caller from a request body, a query or a path.
- Two kinds of accounts live in one user pool: people (`user`) and edge devices (`device`).
- Every record in the business databases belongs to a **user account**, its owner. A device writes data on
  behalf of its owner.
- The link device → owner is **not** in the token. Each service that needs it keeps its own copy, filled
  from events ([device-events.md](events/device-events.md)).

## 2. Accounts

| Term | Meaning |
|---|---|
| Account | An identity in the Cognito user pool. The `accountId` of an account is its Cognito `sub` |
| User account | A person using the web application. Group `users`. Owns data |
| Device account | A Raspberry Pi. Group `devices`. Its `sub` is the `deviceId`. Belongs to exactly one user account (1:1 today) |
| Owner | The user account a device belongs to |

Naming pitfall, because the word "account" is used in two ways:

- In data (database columns, events, API fields) `accountId` always means the **owning user account**.
- The header `X-Account-Id` is the **caller's own** account id. It equals the owner only when the caller is a
  `user`. For a `device` it is the `deviceId`. Services must read `X-Account-Type` before using it as an owner.

## 3. Cognito

- One user pool (Essentials tier, which the pre token generation trigger needs to change access tokens).
  Nobody signs up on their own: administrators create the users.
- Groups `users` and `devices`. Membership is assigned by the backend only and a client cannot change it.
  Every account is in exactly one group.
- Two public app clients (no secret): `web` for people, `device` for edge nodes.
- A pre token generation trigger (version 2) maps the group of the user to the claim `account_type`
  (`user` or `device`) in the ID token and the access token.
- Claims services rely on: `sub`, `client_id` (the app client), `account_type`.
- Devices sign in with a username and password over TLS and keep a refresh token (the bootstrap flow). The
  credentials are generated at pairing and stored on the device, never in the repository.
- The pool has no custom attribute describing the account. The bootstrap attribute `custom:account_id` is
  gone from the Terraform configuration and nothing reads it (see section 9 for what happens to the pool).

## 4. API Gateway

One HTTP API in front of all services and functions. Each route names an authorizer, and an authorizer is a
list of app clients whose access tokens it accepts:

| Authorizer | Accepts tokens of | Used by |
|---|---|---|
| `users` | `web` | views, user-only endpoints |
| `devices` | `device` | ingest |
| `users_and_devices` | `web` and `device` | endpoints used by both (alerts, device configuration) |

For service routes the gateway injects these headers, overwriting anything the client sent:

| Header | Value |
|---|---|
| `X-Account-Id` | `sub` of the token (the caller's own account id) |
| `X-Account-Type` | claim `account_type` (`user` or `device`) |

Lambda integrations receive the claims in the request context instead of headers.

The pairing endpoint of device-management is exposed on a separate route (`/api/v1/admin/...`) with **IAM
authorization** (AWS Signature V4): only an administrator with AWS credentials can call it, and no Cognito
token opens it. There is no token on such a route, so the gateway sets `X-Account-Type: iam` and
`X-Account-Id` to the ARN of the calling IAM principal (useful in audit logs), overwriting whatever the
client sent.

## 5. Authorization rules

The **owner** of a request is resolved like this: a `user` caller is its own owner (`X-Account-Id`), a
`device` caller is resolved through the pairing table of the service (`deviceId` → `accountId`).

| Endpoint | Callers | Rule |
|---|---|---|
| `POST /api/v1/ingest/*` | device | Identity from the token only (`sub` = `deviceId`). The Lambda also requires `account_type = device` |
| Views (`/api/v1/views/*`) | user | Data filtered by the caller's own account |
| Alerts (`/api/v1/alerts*`) | user and device | Alerts belong to the user account. A user works on their own alerts. A device reads the alerts of its owner, so every device of one account gets the same list |
| `/api/v1/devices/{deviceId}/...` (configuration, heartbeat, status) | user and device | Device: `{deviceId}` must equal `X-Account-Id`. User: the device must be owned by `X-Account-Id`. Anything else is refused |
| Image upload URLs (`/api/v1/images/presigned-urls`) | device | Keys are scoped to the caller's `deviceId` (final key layout is an open point of the ingest documents) |
| Pairing of devices (device-management) | administrator | IAM (SigV4) |

## 6. Where the link is stored

Both services that need to know the owner of a device keep their own copy. Exact schemas belong to the
services.

- **device-management** (DynamoDB): one item per device with `deviceId` (key), `accountId` (owner) and
  `version`, plus an index by `accountId` so the UI can list the devices of a user. It is the source of
  truth and the only writer.
- **operations** (PostgreSQL): table `accounts` (`account_id` = the `sub` of a user) and table `devices`
  (`device_id`, `account_id`, `version`), filled from events. While the rule is 1:1, `account_id` is unique
  in `devices`; going to several devices per account later is a migration that drops that constraint.
- Business tables (detections, device locations) carry both `account_id` (the owner at the time of writing)
  and `device_id` (the source). When a device changes owner, history stays with the previous owner.
- A row in `accounts` is created by an idempotent upsert on the first authenticated request of a user, and
  also when a `device.paired` event names an account that is not there yet. Profile data (name, e-mail)
  stays in Cognito.

## 7. Pairing

An administrator pairs a device with a user through device-management, which owns the device registry.
For now a script calls the endpoint. The OpenAPI contract is written later.

1. The administrator calls the pairing endpoint (SigV4) with the `accountId` of the user.
2. device-management creates the Cognito user of the device and adds it to the group `devices`. Cognito
   returns its `sub`: that is the `deviceId`.
3. device-management writes the device item (`deviceId`, `accountId`, `version = 1`).
4. **After the write** it publishes `device.paired` to the SNS topic `device-events`.
5. It returns the `deviceId` and the generated credentials to the administrator. The credentials are shown
   once and go onto the device.
6. operations receives the event from its own queue and upserts `accounts` and `devices`.

Changing the owner or unpairing uses the same endpoint family. Every change raises `version` and publishes
`device.paired` (new owner) or `device.unpaired`. Events, delivery and failure handling are described in
[device-events.md](events/device-events.md).

## 8. Runtime flows

**A device sends data.** It signs in and gets an access token (`account_type = device`, `sub` = `deviceId`).
It calls `POST /api/v1/ingest/...`; the `devices` authorizer validates the token; the Lambda validates the
body and publishes it to SNS with the attribute `deviceId`; the queue of operations delivers it; the
consumer resolves the owner of the device in its `devices` table and stores the record with `account_id`
and `device_id`.

**A user opens the application.** The `web` client signs in. Views filter by `account_id = X-Account-Id`
with no lookup. device-management finds the devices of the user by the index on `accountId`.

**A device reads alerts.** The device calls `GET /api/v1/alerts` with its token. The service resolves the
owner of the device and returns the alerts of that account (supports `ETag` / `If-None-Match`).

## 9. Changes to the bootstrap

The rows about infrastructure (user pool, gateway, routes, ingest Lambda, messaging, task role permissions)
are written in `infrastructure/` and were reviewed with `terraform plan`; they are **not applied yet**. The
rows about service code are not started.

| Area | Bootstrap | Target |
|---|---|---|
| User pool | Immutable attribute `custom:account_id`; trigger copies it into the claim `account_id` | Groups `users` / `devices`; trigger writes `account_type`; no account attribute (see below) |
| Gateway headers | `X-Account-Id` from claim `account_id`, `X-User-Id` from `sub` | `X-Account-Id` from `sub`, `X-Account-Type` from `account_type`; `X-User-Id` is dropped |
| Routes | Alerts of a device at `/api/v1/devices/{deviceId}/alerts` behind `users` | `GET /api/v1/alerts` behind `users_and_devices` (other alert methods stay behind `users`); `/api/v1/admin/*` of device-management with IAM authorization |
| Ingest Lambda | Needs claims `account_id` and `sub`; publishes `accountId` and `deviceId` | Needs `sub` and `account_type = device`; publishes `deviceId` only; validates the body (see the ingest documents) |
| Messaging | Topic `edge-events` and one queue for operations | Adds topic `device-events` (only the task role of device-management may publish) and queue `operations-device-events` with a DLQ (5 receives, 14 days retention) |
| device-management | No endpoint, tables only | Pairing endpoint; task role may create device users in the pool, publish to `device-events` and use the topic key |
| operations | `CurrentAccount` reads `X-Account-Id` as the owner | Reads `X-Account-Type`, resolves the owner of a device caller; tables `accounts` and `devices`; consumer of `device-events` |
| `CLAUDE.md` | Local apps may connect to SNS/SQS on `dev` | Local apps do not connect to SNS/SQS on AWS (done) |

**The attribute `custom:account_id`.** Cognito does not let a custom attribute be removed from an existing
pool. With the attribute removed from the configuration, `terraform plan` shows an in-place update of the
pool, but applying it fails with `cannot modify or remove schema items`. The way to a clean schema is to
recreate the pool, a deliberate one-off step that was done on `dev` like this:

1. Switch `deletion_protection` of the pool to `INACTIVE` and apply. (The same apply also failed on the
   schema removal, but protection was already switched off by then.)
2. Apply with `"-replace=module.user_pool.aws_cognito_user_pool.this"` (quote the argument in PowerShell).
   The pool, its app clients and groups are recreated, the authorizers of the gateway follow in-place, and
   all users (people and devices) and the app client ids change.
3. Switch `deletion_protection` back to `ACTIVE` and apply.

## 10. Open points

- **Publish failure after the write.** The DynamoDB write can succeed and the SNS publish fail, leaving
  operations without the link. Deliberately postponed. Candidates: an idempotent pairing endpoint that
  always republishes, an administrator action that republishes all pairs, DynamoDB Streams → EventBridge
  Pipes → SNS (to be verified).
- **Unpairing.** Should it also disable or delete the Cognito user of the device? An unpaired device with a
  valid token can still call ingest; its events then end in the DLQ.
- **Device credentials.** Password generation, storage on the Raspberry Pi, rotation and token lifetimes.
- **Several devices per account.** Drop the uniqueness of `account_id` in `devices` and check the
  authorization rules that assume exactly one device.
- **Owner lookup cost.** Services may cache `deviceId` → `accountId` for a short time.
- **Contract of operations-service.** The alerts endpoint, `CurrentAccount` and the removal of
  `/api/v1/devices/{deviceId}/alerts` are aligned when its contract is reviewed.
