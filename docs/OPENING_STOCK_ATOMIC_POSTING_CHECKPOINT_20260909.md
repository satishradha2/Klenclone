# Opening stock and atomic posting checkpoint

Date: 2026-09-09

## Outcome

The checksum-verified opening-stock package was imported into the isolated Asas
ERP operational PostgreSQL database. The current reconciled source evidence
supersedes the earlier provisional minus-171-unit variance: the location stock
and product register now agree exactly, so no additional minus-171 correction
was posted or imported.

BizModo was not modified. The evidence files are mounted read-only, the source
capture remains classified `NON_ATOMIC`, and production posting remains
globally disabled.

## Imported stock and costs

- Source batch: `077c378d7fcee47a8a670b3b582e5051642f60f0c5fbc3ab8fc661ef7c366f16`
- Available positive position rows: 579
- Positive quantity: 29,137.02 base units
- Weighted opening-stock value: AED 174,253.82
- Quarantined negative rows: 4
- Quarantined negative quantity: -13.00 base units
- Reconciled net quantity: 29,124.02 base units across 470 SKUs
- Locations mapped to Asas codes: `MAIN`, `SHJ`, `RAK`, and `DXB`

The importer verifies source-manifest SHA-256 values, reconciles each SKU across
the location and product files, rejects invalid UOM/cost data, refuses a
non-empty target, and uses a deterministic batch identity. Repeating the same
import returned `already_imported` and created no duplicates.

## Fiscal-period governance

Fiscal period `2026-09` was created with an approval reference and actor audit.
It is open for controlled rehearsal only. It does not authorize production
posting.

## Atomic posting and reversal

Migration `0006` adds source-bound opening-stock batches, negative-stock
exceptions, inventory-ledger entries, and governed fiscal-period metadata.

The posting service now performs journal, inventory, reservation, weighted-cost
and subledger changes in one database transaction under a deterministic
idempotency key. The reversal service writes inverse journal, inventory and
subledger records and restores the exact prior stock/cost state. It rejects a
reversal when later stock activity makes exact restoration unsafe.

Both HTTP operations are dual-gated: `ASAS_POSTING_ENABLED` must be true and the
caller must have the dedicated execution permission. The environment flag is
currently false, and the provisioned users do not have those permissions.

## Live verification

- Operational migrations: 6
- Stock positions: 579; all 579 availability-enabled
- Active reservations: 0
- Fiscal periods: 1 open, rehearsal-enabled
- Drafts: 0
- Permanent journal batches/lines: 0 / 0
- Inventory-ledger entries: 0
- Party-subledger entries: 0
- Reversal requests: 0
- Browser smoke test: 579 positions, 0 reservations, 1 open period, 0 postings
- Automated suite: 87 passed, 1 expected isolated-PostgreSQL skip

## Backup and restore proof

- Backup: `var/backups/asas-operational-opening-stock-20260909.dump`
- Size: 77,027 bytes
- SHA-256: `A4104AFC15A2CC6AC24CC86C080E2D21FB2D2A0F6A36FFBDFA45F127A51236B3`
- Restored migrations: 6
- Restored positions: 579; quantity 29,137.02; value AED 174,253.82
- Restored exceptions: 4; quantity -13.00
- Restored batch net: 29,124.02
- Restored fiscal periods: 1
- Restored permanent journals: 0
- The temporary restore database was removed after verification

## Remaining production gates

1. Resolve and approve the four genuine negative-stock exceptions.
2. Opening AR/AP contact controls are now staged; reconcile the three preserved
   header/report exceptions and capture all BizModo transactions and attachments
   created after this non-atomic snapshot.
3. Perform a transaction-free or database-backup cutover capture and reconcile
   it to the staged opening data.
4. Provision segregated poster and reverser roles, approve fiscal-period policy,
   and explicitly enable posting only after cutover acceptance.
