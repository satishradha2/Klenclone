# Application foundation checkpoint

## Result

A local ERP migration control center now runs against the canonical target database. It provides a read-only API and responsive dashboard without exposing operational mutations, authentication, posting or confidential row payloads.

The verified local address is `http://127.0.0.1:8080/`. Binding to loopback prevents remote network access by default.

## API surface

| Endpoint | Purpose | Verified |
|---|---|---:|
| `GET /api/v1/health` | Database/snapshot and safety-mode health | 200 |
| `GET /api/v1/summary` | Aggregate migration counts | 200 |
| `GET /api/v1/coverage` | Per-entity coverage gates | 200 |
| `GET /api/v1/gates` | Financial, security, workflow and coverage gates | 200 |
| `GET /api/v1/exceptions` | Aggregated exception codes/severity | 200 |
| `GET /api/v1/accounting` | Journal/opening status summaries | 200 |
| `GET /api/v1/audit-events` | Redacted immutable audit event list | 200 |
| `GET /api/docs` | Generated OpenAPI documentation | Available locally |

No endpoint for creating, editing, approving, posting, importing, deleting or authenticating is exposed.

## HTTP safety controls

- Only `GET`, `HEAD` and `OPTIONS` requests are accepted.
- POST and other mutating methods return HTTP 405 with a read-only explanation.
- Responses include `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a same-origin Content Security Policy and `Cache-Control: no-store`.
- Exception data is aggregated; underlying business/person payloads are not returned.
- Audit-event details are redacted from the unauthenticated interface.
- The health response explicitly reports `authentication_enabled=false` and `posting_enabled=false`.

## Dashboard

The responsive dashboard displays:

- Controlled snapshot and non-atomic warning.
- 41,444 raw and coverage records.
- 4,976 documents, 18,022 movements and 8,325 journal blueprints.
- 188 migration exception items.
- Financial, security and workflow activation gates.
- Largest source-entity coverage counts.
- Aggregated review-queue categories.
- Recent immutable audit-event metadata.

Visual browser verification confirmed the dashboard renders these live database values, the read-only/non-posting banner is visible and the browser console contains no errors.

## Verification

- `python -m pytest -q` passes 43 tests.
- Source compilation succeeds.
- Six production-data aggregate endpoints return HTTP 200 against the current local snapshot.
- A POST request to the summary route returns HTTP 405.
- Separate temporary-database tests verify health, headers, write rejection and confidential-summary boundaries.

## Current boundary

This is an internal migration-assurance shell. It must remain loopback-only until target authentication, TLS, secrets management, authorization enforcement, deployment hardening and security review are complete. It is not a replacement for final frozen-source extraction or business UAT.
