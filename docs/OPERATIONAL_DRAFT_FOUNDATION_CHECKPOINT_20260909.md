# Operational draft foundation checkpoint

Date: 2026-09-09

## Outcome

Asas ERP now has a physically separate operational PostgreSQL database and an
authenticated draft-entry workspace for sales and purchases. The cloned
BizModo evidence database remains separate and read-only.

- UI route: `http://127.0.0.1:18082/#drafts`
- Operational database: `asas_erp_operational`
- Docker service: `operational-database`
- Host exposure: none
- Supported documents: sales draft and purchase draft
- Supported lines: 1 to 100 per draft
- Currency: AED
- Posting: disabled by database constraint and application policy

## Controls

- A valid authenticated session, CSRF token and action-specific permission are
  required for every operational mutation.
- The operations administrator can create, edit, submit and cancel drafts. The
  independently provisioned approver can approve and run posting rehearsals,
  but cannot create or edit drafts.
- Maker-checker control prevents a draft creator from approving the same
  document.
- Customer/supplier type, product SKU and location are validated against the
  cloned source masters, including the verified provisional overlay.
- Product name, party name and price are snapshotted into the operational draft.
- Quantity must be positive; price cannot be negative; VAT must be between zero
  and 100 percent; discount cannot make the document total negative.
- AED net, VAT and gross amounts use decimal arithmetic and half-up rounding.
- Every successful creation appends an immutable operational audit event.
- Drafts do not create stock movements, journals, tax-ledger entries, payments,
  receivables, payables, or changes in BizModo.

## Separate persistence

The operational database uses its own Docker volume,
`klen-copy-validation_asas_operational_postgres`. It does not share the clone
database volume. At deployment verification the new operational database held
zero drafts, zero lines and zero audit events; no synthetic business document
was left behind.

## Verification

- Operational database health: passed
- Operational schema creation: passed
- Anonymous and missing-CSRF creation rejection: passed
- Master and location validation: passed
- Multi-line model and monetary calculation: passed
- Database-level posting prohibition: passed
- Browser draft-workspace rendering: passed
- Full automated suite: 86 passed, 1 skipped

## Workflow and UOM extension

The second controlled operational increment was applied on the same date.

- Schema versions `0001`, `0002`, `0003` and `0004` are checksum-recorded in
  `operational_schema_migrations`.
- Drafts carry an integer revision; stale edits are rejected instead of
  overwriting another change.
- Drafts can move from `draft` to `submitted`, or from `draft`/`submitted` to
  `cancelled`. Every transition creates immutable workflow and audit events.
- The model includes an `approved` state. A separately authenticated approver
  has been provisioned and maker-checker enforcement prevents the creator from
  approving the same document.
- Each line now preserves entered UOM, canonical UOM,
  `factor_to_base_snapshot`, and `quantity_base`.
- The application enforces
  `quantity_base = entered quantity * factor_to_base_snapshot` and refuses UOMs
  that do not match the captured source/canonical base-unit profile.
- Draft editing, multi-line entry, submission, approval and cancellation controls
  are available according to role. Product, party and location selectors are
  sourced from the clone, and a printable review view shows UOM conversion and
  base-quantity snapshots.
- An approved draft can run a transactional posting rehearsal. It creates a
  balanced control-account journal projection and stock-movement probes inside
  a savepoint, then rolls the probes back and verifies the before/after count.
  It never creates real inventory, journal, VAT, AR or AP entries.

Live operational migration verification confirmed the operational tables, all
four checksummed migration rows, the expanded status constraint, the immutable
posting prohibition, and an empty business database. The final deployed check
showed zero drafts, lines, workflow events and posting probes.

## Remaining gates

1. Move the recorded migration runner into a standalone deployment job so the
   application identity does not require DDL privileges.
2. Reconstruct and reconcile opening stock valuation; current COGS rehearsal
   uses cloned purchase-price evidence as a provisional weighted-average seed.
3. Capture and approve conversion factors for alternate UOMs; the current UI
   accepts only verified base-UOM mappings.
4. Add availability, reservation and negative-stock controls.
5. Implement stock, subledger, VAT and balanced journal posting as a transaction
   with a rollback rehearsal; do not enable it before reconciliation succeeds.
6. Schedule encrypted off-host backups and periodic restore drills; the first
   local PostgreSQL custom-format restore drill passed on 2026-09-09.
