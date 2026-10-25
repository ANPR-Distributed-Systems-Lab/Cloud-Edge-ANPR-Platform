# operations-service — delta rules

Extends the root `CLAUDE.md`. Root rules win on conflict. Code wins over this file; if they disagree, fix the file.

Business layer microservice (diagram name: "Mikroserwis 2 / Alerts-And-Views-Service"): Views 1, 2, 3, 6, alert CRUD, alert list for edge devices, consumer of detection and device-location events. Owns its PostgreSQL/PostGIS database; nobody else writes to it.

## 0. Scope (from the architecture diagram)

**Source of truth for views 1–6** (description, response payload, indexing requirements, agreed deviations): [`docs/views-specification.md`](../docs/views-specification.md). Read it before changing the contract, schema or queries. Any new deviation from the diagram is added to its "Odstępstwa" table.

Endpoints defined on the diagram — the contract must cover exactly these:

| Endpoint | View | Purpose |
|---|---|---|
| `GET /api/v1/views/anpr-search` | 1 | Plate search with autocomplete and time filter (map pins, table, photo gallery) |
| `GET /api/v1/views/radial-analysis` | 2 | Detections within X metres of a point + device GPS track in the same time window |
| `GET /api/v1/views/live-feed` | 3 | Latest detections + device positions/track from the last 20 minutes |
| `GET /api/v1/alerts` | 6 | Alert list, sortable by created date and last triggered date |
| `POST /api/v1/alerts` | 6 | Create alert for a plate |
| `PUT /api/v1/alerts/{alertId}` | 6 | Update alert |
| `DELETE /api/v1/alerts/{alertId}` | 6 | Delete alert |
| `GET /api/v1/alerts/{alertId}/detections` | 6 | Detection history linked to an alert |
| `GET /api/v1/devices/{deviceId}/alerts` | IoT | Alert list synced by Raspberry Pi |

- Additions not on the diagram, **pending agreement with the teammate** (then add them to the diagram, or remove from the contract): `GET /api/v1/alerts/{alertId}` (edit form, refresh after 409) and `GET /api/v1/views/anpr-search/plate-suggestions` (lightweight autocomplete). Fallback if rejected: autocomplete as a parameter of `anpr-search`.
- Out of scope: Views 4 (Raspberry Pi settings) and 5 (device health) — DynamoDB, another service. The frontend (same owner) consumes that service's contract.
- Diagram response fields include `id_konta`; the contract omits it from responses (D3) and it is never an input parameter (see section 2).
- Gallery (View 1): the contract returns a presigned GET `imageUrl` instead of `s3_key` (D4, proposal).
- Indexes: the diagram lists single-column B-Trees; we use composite indexes `(account_id, detected_at)` etc. (D1, section 5) — a deliberate design decision for the thesis.
- Deviations are referenced in the contract as `D1`..`D10` — never write `#` after a space in an unquoted YAML string (it starts a comment and truncates the text).
- Naming is open: diagram says "Alerts-And-Views-Service", repo directory is `operations-service`.

## 1. Package layout

```
com.anpr.operations
├── api/<area>/           what we expose: controllers (implement generated OpenAPI interfaces), facades, converters
├── messaging/<topic>/    inbound SQS listeners + message DTOs (someone else's contract), outbound SNS publishers
├── internal/<area>/      domain: services, repositories, entities, enums — no HTTP, no SQS, no generated DTOs
├── config/               @ConfigurationProperties, beans, SSM wiring
└── shared/               cross-area helpers (masking, clock) — justify every file added here
```

Areas: `search` (View 1), `radial` (View 2), `livefeed` (View 3), `alerts` (View 6 + device alert list), `detections`, `locations`.

- Split by business area, not by class kind.
- `internal/` never imports from `api/` or `messaging/`. Message DTOs and generated API DTOs are converted at the boundary.
- Entities never leave `internal/`. Responses are always generated OpenAPI models, mapped with MapStruct (`@Mapper`), never field by field in a service.
- Controller = take request, call one facade/service method, return. No business conditions.
- Facade only when an operation composes more than one source. One delegation = call the service directly.

## 2. Contract first (OpenAPI)

- `operations-api.yaml` (service root) is the source of truth. Controllers and DTOs are generated into `target/` (gitignored).
- Separate schemas for create, update and response (`CreateAlertRequest`, `UpdateAlertRequest`, `AlertResponse`). Never one shared object.
- Every list endpoint is paginated with an upper bound (`size` max 100). Sort fields are enums, never free text.
- Account identity comes from the API Gateway injected header (JWT claims), never from a path/query/body parameter.
- `GET /devices/{deviceId}/alerts` must verify the device belongs to the caller's account and supports `ETag` / `If-None-Match`.
- A contract change ships in one PR: yaml + backend + regenerated frontend client + tests.
- Backward compatible only: add fields, never rename/remove. Breaking change = new version path.

## 3. Errors

- One error body for the whole API: Spring `ProblemDetail` (RFC 9457) with extension fields `code` (stable, machine-readable), `requestId` (= trace id) and optional `fields[]` for validation.
- Standard HTTP statuses only: 400 malformed/validation, 404 not found, 409 business conflict (incl. optimistic lock), 500 unexpected. No custom 5xx codes.
- Exception hierarchy: `BusinessException` (client's fault, logged at INFO), `NotFoundException`, `TechnicalException` (our fault, logged at ERROR with cause). All unchecked.
- One `@RestControllerAdvice` with a catch-all `Exception` handler. Responses never contain stack traces, class/package names, SQL, table names or hostnames.
- Error codes live in one catalog class (`ErrorCodes`). Codes are a contract; messages may change. Frontend reacts to `code`, translates it itself.
- Always pass the cause when wrapping an exception.

## 4. Validation

- Level 1 (unreadable body) and level 2 (format/range, data alone) → Bean Validation annotations, generated from OpenAPI constraints. Nested objects need `@Valid`.
- Level 3 (needs DB state, e.g. duplicate alert for plate) → service, inside the same transaction as the write.
- DB constraints are a safety net, never the source of the user-facing message.

## 5. Data and transactions

- Schema only via Flyway. Never edit a migration that has been merged. Changes follow expand → migrate → contract.
- `ddl-auto: validate`.
- Coordinates as `geography(Point, 4326)` so `ST_DWithin` works in metres; GiST index on them.
- Composite indexes matching real queries, e.g. `(account_id, detected_at DESC)`, `(account_id, plate, detected_at DESC)`; `pg_trgm` GIN for plate autocomplete.
- `@Transactional(readOnly = true)` on every read path.
- Transaction boundary = business operation, in the service or facade. Never in controllers or repositories.
- No network calls (SNS, S3, HTTP) inside a transaction. Publish events with `@TransactionalEventListener(phase = AFTER_COMMIT)`. Known gap (commit ok, publish failed) is documented; transactional outbox is the upgrade path.
- `@Version` on entities edited by users (`alerts`). Optimistic lock failure → 409 `CONCURRENT_MODIFICATION`.
- Proxy rules: `@Transactional` only on public, non-final methods, never called via `this` from the same class. Extract a separate bean instead.

## 6. SQS consumers

- Delivery is at-least-once. Every consumer is idempotent: detections are keyed by the edge-generated `detection_id` (unique constraint + `ON CONFLICT DO NOTHING`).
- Alert matching (set `alert_id`, update `last_detected_at`) happens in the same transaction as the insert; the resulting change is published to SNS after commit (root rule: modified record → event).
- A message that fails N times goes to the DLQ; one poison message must not block the queue.
- Trace id is read from message attributes into MDC and cleared in `finally`.

## 7. Concurrency

- Beans are stateless: every field `final`, pointing to an immutable or thread-safe object.
- No `ThreadLocal` / MDC writes without clearing in `finally`.
- Every outbound call has connect and read timeouts.

## 8. Logging and personal data

- JSON logs only, every line carries `traceId` (root rule).
- License plates and GPS positions are personal data (GDPR). Log plates only through `PlateMasker.mask()` (e.g. `WA1****`), never coordinates together with a plate. Validate any new "is this sensitive?" decision before coding.
- Hot request paths log at DEBUG. ERROR only for real technical failures.
- No silent fallbacks: a default used because a value is missing is logged at WARN.

## 9. Configuration

- Environment values come from `application.yml` + SSM Parameter Store via `@ConfigurationProperties`. No `static final` URLs, ids or limits.
- A new property is added to every profile file and to the example config in the same change.
- Missing required config fails startup. Defaults must be the safest value, not the most convenient.

## 10. Tests

- Testcontainers with `postgis/postgis` for repositories, migrations and consumers. AWS (SNS/SQS/Cognito) is mocked in internal tests.
- Each test must fail without the fix. Check it once by breaking the code.
- Required test types:
  - error body contains no `com.anpr` string and has `code` + `requestId`,
  - operation failing halfway leaves nothing in the DB,
  - the same SQS message twice produces one row,
  - account A cannot read account B's data,
  - contract shape (field names) of each response.
- Expected JSON payloads live in `src/test/resources/<area>/`, not inline.
- Before calling a failure "mine": `git stash`, rebuild, rerun, compare.

## 11. Environment pitfalls

- After changing the OpenAPI yaml or switching branches: `./mvnw clean compile` before diagnosing any "cannot find symbol" (stale generated code / MapStruct impls).
- "Port already in use" = old instance still running. Kill it, don't change the port.
- Reproduce an external call (curl, `aws sqs send-message`) before debugging application code.

## 12. Git and review

- Branches `feature/...`, `fix/...`; Conventional Commits in English, one line; reasoning goes in the PR description (Problem / Cause / Fix / How to test).
- `git add` with an explicit file list, never `git add .`.
- Self-review the full diff before commit: dead code, unused imports, whole-file diffs (EOL), PII in logs, conflict markers, test-only hacks (disabled guards, changed URLs).
- Stay in scope. Unrelated findings become separate issues.
- `--force-with-lease` only, never plain force push.

## 13. Working with AI

- AI writes no commits and never pushes; the human commits.
- Plan first (show before/after), implement after approval.
- Domain assumptions (naming, data sensitivity, contract shape) are asked, not guessed. Unverified claims are labelled as assumptions.
