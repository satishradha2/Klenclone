# Stock, period and posting controls checkpoint

Date: 2026-09-09

## Outcome

Asas ERP now has a non-posting enterprise control layer for stock availability,
reservations, fiscal periods, deterministic posting identity, permanent journal
and subledger schemas, and reversal projections. Migration `0005` is deployed.
BizModo was not modified and no operational business rows were created.

## Stock controls

- Stock positions are unique by location and SKU and preserve canonical UOM,
  on-hand quantity, reserved quantity, weighted-average cost and revision.
- Database constraints prohibit negative on-hand/reserved quantities and prevent
  reserved quantity from exceeding on-hand quantity.
- Submitting a sales draft locks the applicable stock-position rows and creates
  one reservation per draft line.
- Insufficient, missing or UOM-incompatible stock blocks submission.
- Cancelling a submitted sales draft releases each active reservation and
  restores availability under the same row locks.
- Approval and rehearsal require reservations to cover every sales line.
- Purchase drafts do not reserve outbound stock.

This initial checkpoint has been superseded by the controlled import recorded in
`OPENING_STOCK_ATOMIC_POSTING_CHECKPOINT_20260909.md`. The current live staging
database has 579 availability-enabled positive positions. Four genuine negative
rows remain quarantined. Fresh source reconciliation showed no SKU difference,
so the earlier provisional minus-171-unit correction was not applied.

## Fiscal and posting controls

- Posting rehearsal requires an explicit fiscal period covering the document
  date with status `open` and `rehearsal_enabled=true`.
- Locked, missing or disabled periods block rehearsal.
- Each posting plan has a deterministic SHA-256 fingerprint and an idempotency
  key derived from draft identity, revision and plan fingerprint.
- Permanent journal-batch, journal-line and party-subledger schemas now exist,
  including a unique idempotency-key constraint.
- Reversal-request schema exists with controlled states.
- Each rehearsal returns a balanced inverse journal and inverse stock/value
  movement projection suitable for later reversal validation.
- Atomic posting and exact reversal endpoints now exist behind both a global
  disabled flag and dedicated permissions. No permanent rows have been created.

## Verification

- Automated suite at this checkpoint: 86 passed, 1 skipped
- Superseding opening-stock/posting suite: 87 passed, 1 skipped
- Exact-availability reservation: passed
- Reservation release on cancellation: passed
- Fiscal-period lock rejection: passed
- COGS and inventory-value balance: passed
- Deterministic posting fingerprint: passed
- Balanced reversal projection: passed
- Live Docker health: passed
- Browser control metrics: passed
- Live permanent postings, subledger rows, reversals and probes: zero

## Backup and restore

- Backup: `var/backups/asas-operational-controls-20260909.dump`
- Size: 54,206 bytes
- SHA-256: `F05EEFB5E156FD0392206CDD3605405FBD21847F2EF173CC1DB40222010F7559`
- Restored migration rows: 5
- All new control/ledger tables restored with matching zero row counts
- Temporary restore database was removed after verification

## Remaining gates

1. Resolve and approve the four quarantined negative-stock exceptions.
2. Reconcile AR/AP and the remaining BizModo transaction/attachment delta.
3. Complete an atomic final source capture and cutover reconciliation.
4. Provision segregated posting/reversal roles and explicitly activate posting
   only after production approval.
