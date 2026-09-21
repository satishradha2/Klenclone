# Cross-project contamination audit — 2026-09-09

## Finding

The browser application exposed at `http://127.0.0.1:8280` is not the BizModo clone. Docker identifies it as the frontend from:

`D:\Klen+ ERP\docker-compose.staging.yml`

The intended clone workspace is `D:\Klen Clone`. Its Docker project is `klen-copy-validation`, and its current UI on port `18081` is a read-only migration-assurance control center rather than a finished operational ERP.

## What remains valid

- The authenticated, read-only BizModo captures under `source_exports/`.
- The local clone and provenance database under `var/klen_staging.db`.
- The `klen-copy-validation` PostgreSQL copy and control-center service.
- Reconciliation calculations and checksum-bound evidence, provided they are treated as clone migration evidence rather than proof that the other ERP is the target application.
- Live BizModo was not changed by the cross-project operations.

## Confirmed impact on the separate KLEN+ ERP project

### Staging database

The following foreign batches were inserted into the `klen-erp-staging-v18` PostgreSQL database:

| Prefix | Effect |
| --- | --- |
| `RHR-20260909081833` | Posted 465 products, 794 customers and 88 suppliers. |
| `ROPN-20260909095445` | Added validated-only AR, AP and stock import batches; no business posting. |
| `RREF-20260909-1031` | Posted five additional products, 196 receivables, 53 payables, 30 advance GL lines, 579 positive-stock rows and four negative-stock exceptions. |

After the last posting, the separate project's staging database contained 204 customer invoices, 53 supplier invoices, 268 journal entries, 590 stock movements, 583 inventory-balance rows and four migration inventory exceptions. These figures must not be represented as the new clone application's database.

### Source files

The following changes in `D:\Klen+ ERP` are confirmed to have been made for this incorrect integration path:

- `backend/app/api/data_migration.py`
- `backend/tests/test_data_migration_composite_keys.py`
- `db/migrations/0088_negative_stock_migration_exceptions.sql`

The KLEN+ ERP worktree already contains many unrelated user changes. Recovery must therefore be restricted to confirmed files and must not use a broad reset.

### Clone-workspace artifacts tied to the wrong target

The ERP rehearsal and posting scripts created on 2026-09-09 target the separate KLEN+ ERP schema. Their reports are useful as audit evidence but are not completion evidence for the BizModo clone. In particular:

- `scripts/rehearse_erp_master_import.py`
- `scripts/promote_erp_master_batches.py`
- `scripts/rehearse_erp_opening_import.py`
- `scripts/rehearse_erp_reconciliation_refresh.py`
- `scripts/stage_erp_reconciliation_refresh.py`
- `scripts/rehearse_erp_refresh_posting.py`
- `scripts/post_erp_reconciliation_refresh.py`
- `docs/ERP_MASTER_IMPORT_REHEARSAL_CHECKPOINT.md`
- `docs/ERP_OPENING_REHEARSAL_CHECKPOINT.md`
- `docs/ERP_RECONCILIATION_REFRESH_20260909.md`

These artifacts should be quarantined from the future clone application design after the separate project is recovered.

## Verified recovery point

The earliest clean staging backup is:

`var/erp_import_rehearsals/20260909T081310Z/pre-import-staging.dump`

- Archive creation: 2026-09-09 08:18:30 UTC.
- First foreign batches: 2026-09-09 08:18:33 UTC.
- SHA-256: `B11889A59C34F389A15D429664A9138E682794A46CFB2FECDE7BDA23B56DD382`.
- PostgreSQL custom archive validation succeeded; it contains 2,200 table-of-contents entries and identifies the source database as `klen_erp_staging`.

## Safe recovery sequence

1. Take one additional forensic backup of the currently contaminated KLEN+ staging database.
2. Stop only the `klen-erp-staging-v18` application services.
3. Restore the verified pre-import backup into that staging database.
4. Reapply only legitimate KLEN+ changes made after 08:18:30 UTC, if any are identified.
5. Verify row counts, schema migrations, health and a KLEN+ smoke test.
6. Revert only the three confirmed cross-project source files, preserving every unrelated dirty-worktree change.
7. Keep the BizModo evidence in `D:\Klen Clone`, design and build its own operational application there, and assign it distinct Docker project names, ports, database names and branding.

## Recovery execution

Recovery was explicitly authorized and completed on 2026-09-09.

- A forensic backup of the contaminated staging database was saved as `var/cross_project_recovery/20260909/klen-erp-contaminated-before-recovery.dump`.
- Forensic-backup SHA-256: `8C1B36A10B56472F59E3131DB38381BCCD78F3FD84979F7AF548F8DC1C30A814`.
- Only the `klen_erp_staging` database schema was replaced from the verified pre-import archive.
- All foreign `RHR-*`, `ROPN-*` and `RREF-*` batches are absent after restoration.
- Restored counts are 2 products, 3 partners, 8 customer invoices, 0 supplier invoices, 4 journal entries, 11 stock movements and 4 inventory balances.
- The foreign `migration_inventory_exceptions` table is absent; the latest applied migration is the legitimate `0087_warehouse_pick_recovery.sql`.
- The three confirmed source-file changes were reverted with no focused Git diff remaining.
- The KLEN+ staging services were rebuilt and restarted from the recovered database and source.
- Cross-project bridge scripts and their three checkpoint documents in this workspace are marked retracted/fail-closed to prevent reuse.

Live BizModo, the separate project's production environment, and unrelated KLEN+ worktree changes were not modified.

## Independent clone follow-up

After recovery, a separate read-only Asas ERP preview was created inside this
workspace and assigned port `18082`. At this historical checkpoint it read only
the clone database and excluded HR/payroll. HRM has since been added as a
separately authorized target-ERP workspace while payroll remains excluded. It
has no dependency on `D:\Klen+ ERP`.
Its baseline and remaining production gates are recorded in
`docs/INDEPENDENT_ERP_PREVIEW_CHECKPOINT_20260909.md`.
