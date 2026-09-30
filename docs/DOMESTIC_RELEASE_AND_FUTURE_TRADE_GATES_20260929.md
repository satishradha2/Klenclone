# Domestic ERP release versus future foreign trade (2026-09-29)

## Decision boundary

BizModo has no historical foreign sales or purchases in this clone scope. The SAR/KWD records used for validation are synthetic. Foreign-trade issuance, settlement, tax finalization and FX accounting are **future activation gates**, not prerequisites for accepting existing domestic AED workflows. They remain disabled until policy, evidence, implementation and named business UAT exist for the first real transaction.

The domestic ERP is **not yet approved for production**. Its separate gates remain final source freeze/recapture, resolution or approved treatment of source-data discrepancies, target backup and restore, complete import and row/checksum reconciliation, production infrastructure/security, named business acceptance and explicit cutover/posting authorization. No synthetic foreign record can satisfy those domestic gates.

## Operational PostgreSQL migration rehearsal

Production web startup now verifies operational schema contract revision `0062` without issuing schema-creation or ALTER statements. The preflight checks the recorded checksum and physical tables, column names, types and nullability. Schema upgrades are run separately with `python -m klen_clone.operational_migrate`. The command requires an accessible PostgreSQL custom-format `pg_dump -Fc` archive for an existing database and reports its SHA-256. An empty database does not need a prior backup. A migrated database is checked without reapplying the legacy upgrade. The current revision is a checked baseline over the legacy `0001`–`0061` initializer; any future model change needs a new explicit revision before production can start.

The isolated rehearsal used the synthetic SAR operational database, **not** the shared staging operational database:

1. `pg_dump -Fc` created `var/operational-migration-rehearsal-20260929/sa-before.dump` (SHA-256 `06e08817979dd0c8bd3128ebd6f69a04c9414cf4f2fdcaa5a30b5eb5833ff569`).
2. `pg_restore --exit-on-error` restored that archive to fresh migration and rollback databases. Exact row counts matched the source across all **183** operational tables.
3. The explicit migration advanced only the migration copy from `0061` to `0062`; the read-only verifier passed. Exact business-table row counts still matched across **182** tables; the only intended count change was the migration ledger.
4. Running migration on the rollback copy without a backup file failed closed and left it at `0061`. The read-only production preflight also rejected that unmigrated copy. The rollback copy preserved the original data and schema revision.
5. A separate fresh PostgreSQL integration test proved migration idempotence, read-only preflight and rejection of an altered column type, followed by restoration of the expected type (`1 passed`).

This proves the isolated upgrade and restore mechanics, not an approved production rollback plan. Before any production migration, take and independently restore a new backup of that exact target, record a maintenance window, approval and rollback point, and use the immutable release image and its matching schema contract. Do not run this command against BizModo or the shared operational database as part of this checkpoint.

## Status

After this migration change, the full local Python regression suite passed (**292 passed, 2 skipped**; the PostgreSQL integration tests are opt-in). The frontend suite passed **37/37**. Focused migration/security checks passed **9/9**, and the new isolated PostgreSQL migration test passed **1/1**. Production remains disabled and posting remains locked. The foreign-trade UAT gate is deferred until real foreign business exists, without granting permission to bypass it later.
