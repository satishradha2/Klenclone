# Runtime Architecture Checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Checkpoint date: 2026-09-08  
Source-system rule: live BizModo remains read-only.

## Outcome

The clone now has a production-oriented but deliberately inactive runtime foundation. It adds versioned database migrations, environment validation, disabled authentication principals, permission and location dependencies, approval transition rules, protected detail APIs, runtime module metadata and explicit activation gates. It does not make the ERP operational.

## Runtime inventory

| Control | Count | Active |
|---|---:|---:|
| Migrated authentication principals | 16 | 0 |
| Workflow definitions | 4 | 0 executable |
| Runtime modules | 8 | 0 operational |
| Runtime activation gates | 7 | 0 passed |
| Approval requests | 0 | 0 |

Repeated runtime construction created zero new records, confirming idempotent seeding for this snapshot.

## Safety posture

- Migrated users are unprovisioned and cannot authenticate.
- Authentication is disabled by default and has no login or password-provisioning route.
- Password material, if provisioned later through an approved process, uses PBKDF2-SHA256 with per-password salt; bearer tokens use signed HMAC claims and expiry.
- Protected endpoints require an active principal, enabled role assignment, enabled permission grant and at least one active location scope.
- Workflow execution is disabled; transition validation refuses execution while disabled.
- Every non-GET/HEAD/OPTIONS HTTP request remains rejected by the application.
- There is no document-posting, approval-execution, write-back or BizModo mutation route.
- Production mode refuses non-PostgreSQL configuration and authentication refuses an absent or short signing secret.

## Protected read models

The runtime defines protected party, product and document detail APIs. With the default safe configuration they return HTTP `503` because target authentication is not activated. Aggregate migration-assurance endpoints remain readable on loopback for verification.

## Versioned schema rehearsal

Alembic revision `20260908_0001` was applied to a separate empty SQLite rehearsal database. It reached `head`, produced 88 tables and contained the required authentication, module, approval and migration-version tables. The disposable rehearsal database was then removed. The populated clone database was not used or stamped.

The baseline is suitable for building a new empty database. Applying or stamping an already populated database requires a separate schema-diff review and an approved, backed-up procedure.

## Blocked activation gates

- Authentication principal provisioning: 16 users require controlled provisioning.
- PostgreSQL deployment: shared target database is not deployed.
- RBAC enforcement: target enforcement is not approved active.
- Location-scope enforcement: target enforcement is not approved active.
- Workflow approval: 4 workflow definitions remain disabled.
- TLS and secrets: production secret and transport controls are not deployed.
- Frozen cutover: no transaction-free cutover window or hosting-level backup is available.

## Verification

- Python compilation: passed.
- Automated tests: 46 passed.
- Runtime rerun: zero new records.
- Migration rehearsal: revision at head; required tables present.
- Rendered UI: Overview loaded with seven locked operational workspaces, 29 blocked gates and 0 active gates; browser warning/error log was empty.
- Source-system writes: none.

## Next controlled stage

Build and verify deployment packaging plus read-only module workspaces against the cloned database. Principal provisioning, approval execution and posting remain outside scope until PostgreSQL, secrets, TLS, role/location sign-off, reconciled cutover evidence and business UAT are complete.
