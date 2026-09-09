# SQLite to PostgreSQL Copy Checkpoint

Copy date: 2026-09-09  
Source snapshot: `bizmodo-2026-09-08-browser`  
Target compose project: `klen-copy-validation`  
Target exposure: control center on loopback only; PostgreSQL port not published.

## Outcome

The complete local SQLite clone was copied into a new isolated PostgreSQL 17 database. All application tables were copied inside one target transaction and verified before commit. The live BizModo website was not accessed or changed during this operation.

This proves exact transfer from the existing local clone. It does not convert the earlier non-atomic browser extraction into an atomic source-system backup; that final limitation still requires a frozen cutover window or hosting-level database/file backup.

## Guardrails

- Explicit SQLite source file mounted into the copy container as read-only.
- SQLite connection set to `PRAGMA query_only = ON`.
- Target required to be PostgreSQL and contain zero application rows.
- PostgreSQL advisory transaction lock prevented a concurrent copy.
- Tables copied in SQLAlchemy dependency order with original primary keys preserved.
- PostgreSQL identity sequences reseeded to copied maxima.
- Per-table source and target counts plus normalized content hashes compared before commit.
- Any mismatch raises an error and rolls back the entire target transaction.

## Reconciliation result

| Control | Result |
|---|---:|
| Application tables verified | 87 |
| Total stored rows copied and verified | 367,688 |
| Overall table-manifest SHA-256 | `c29bfffa45c86928dac7c43c5bdfaebc013c2c635f8ce82b0a8492bcf932c8fe` |
| Raw records | 41,444 |
| Source coverage records | 41,444 |
| Source key registry records | 41,444 |
| Transaction documents | 4,976 |
| Inventory movements | 18,022 |
| Journal blueprints | 8,325 |
| Migration exceptions | 188 |
| Authentication principals | 16 |
| Active principals | 0 |

The 367,688 figure is the sum across raw evidence, typed staging, provenance, canonical ERP structures and runtime-control tables. It is not a count of distinct source records.

## Source immutability evidence

The SQLite file was measured before and after the copy:

| Property | Before | After |
|---|---|---|
| Bytes | 129,785,856 | 129,785,856 |
| Modified UTC | 2026-09-08T19:10:44.1899220Z | 2026-09-08T19:10:44.1899220Z |
| SHA-256 | `1bbaab2abdd0c51481747e5956098e61f67da1cd603bb735a48d704a56c42c62` | `1bbaab2abdd0c51481747e5956098e61f67da1cd603bb735a48d704a56c42c62` |

All three properties matched exactly.

## Application verification

The PostgreSQL-backed control center reached healthy status at `127.0.0.1:18081`. API and rendered-browser checks matched the SQLite clone:

- 41,444 raw records and 41,444 coverage records.
- 4,976 documents, 18,022 movements, 8,325 journals and 188 exceptions.
- 74 gates, including 29 blocked and 0 active.
- 16 authentication principals and 0 active principals.
- Protected document detail returned HTTP 503.
- A mutating summary request returned HTTP 405.
- Browser warning/error log was empty.

The original SQLite dashboard was restored on `127.0.0.1:8080`; both SQLite and PostgreSQL views currently report the same record and coverage totals.

## Current custody and limitations

The verified PostgreSQL copy remains in the local Docker named volume `klen-copy-validation_klen_postgres` for the next controlled stage. It contains confidential cloned business data. The database has no published host port, the UI is loopback-only, authentication is disabled, and no posting endpoint exists.

The environment variable name required to recreate services is `KLEN_POSTGRES_PASSWORD`; its value must not be committed to source control. This local validation copy is not yet a backed-up production deployment.

## Next controlled stage

Build authenticated read-only list and detail views using synthetic principals first, then conduct business UAT against the PostgreSQL copy with explicitly approved user and location assignments. Posting, approvals and source write-back remain disabled.
