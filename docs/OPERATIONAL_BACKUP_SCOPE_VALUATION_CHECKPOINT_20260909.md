# Operational backup, scope and valuation checkpoint

Date: 2026-09-09

## Outcome

The isolated Asas ERP operational service now enforces explicit location scope,
captures a line-level cost basis, includes COGS in sales posting rehearsals, and
has passed a real PostgreSQL backup-and-restore drill. Real posting remains
disabled and BizModo was not modified.

## Location scope

- Both provisioned roles are explicitly scoped to the four cloned locations:
  `DXB`, `MAIN`, `RAK`, and `SHJ`.
- Location selectors return only permitted locations.
- Draft lists, draft detail, transitions, approvals, and posting rehearsals hide
  out-of-scope drafts as not found.
- Draft creation rejects a valid cloned location when it is outside the current
  user's scope.
- Scope is returned in the authenticated principal payload for UI and audit
  visibility.

## Valuation rehearsal

- Operational schema migration `0004` adds `unit_cost_snapshot` and
  `cost_amount` to every draft line.
- The snapshot is derived from cloned purchase-price evidence at draft creation
  or revision time. It is immutable after submission.
- Sales rehearsal produces AR, revenue, output VAT, COGS and inventory journal
  projections. Missing or non-positive cost evidence blocks rehearsal.
- Purchase rehearsal uses the incoming merchandise price and proportionally
  allocates document discount across stock value, with the final line absorbing
  rounding remainder.
- Stock quantity and value probes are written inside a savepoint and rolled back;
  the before/after probe count must match.
- The current cost basis is a provisional weighted-average seed from visible
  purchase-price evidence. It is not yet a reconstructed perpetual valuation
  ledger and cannot authorize production posting.

## Backup and restore evidence

- Backup: `var/backups/asas-operational-20260909.dump`
- Format: PostgreSQL custom archive, no owner
- Size: 23,154 bytes
- SHA-256: `36537067D10574C824C6FD44CFF51920A8862C0334CF67E8ABE75373394437E5`
- Restore target: temporary database `asas_erp_restore_verify_20260909`
- Restored migration rows: 4
- Restored drafts, lines, audit events, workflow events and probes: all matched
  the source counts of zero
- Temporary verification database: removed and confirmed absent

The retained backup and checksum are under `var/`, which is excluded from source
control because future backups may contain confidential operational data.

## Verification

- Full automated suite: 86 passed, 1 skipped
- Docker application and both PostgreSQL services: healthy
- Live operational migrations: `0001`, `0002`, `0003`, `0004`
- Live retained drafts, lines and posting probes: zero
- Authenticated browser draft workspace: passed
- Authenticated API location-scope comparison: passed

## Remaining production gates

1. Move operational DDL into a standalone least-privilege migration job.
2. Reconstruct and reconcile a reliable opening valuation ledger rather than
   relying on purchase-price evidence alone.
3. Load approved stock positions into the new availability/reservation controls.
4. Implement the atomic posting and reversal execution services on the new
   idempotent permanent-ledger schemas.
5. Capture and reconcile the remaining BizModo delta and attachments before
   production cutover.
