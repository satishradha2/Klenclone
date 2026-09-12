# Atomic Posting and Reversal Checkpoint — 2026-09-09

## Outcome

The ERP now has a common controlled posting path for inventory transfers and adjustments, goods receipts, sales returns and credit notes, purchase returns and debit notes, and customer receipts and supplier payments. Sales and purchase drafts continue to use their existing atomic journal posting path.

Permanent posting remains disabled by configuration. This checkpoint adds and validates the posting engine; it does not activate production or change cloned BizModo evidence.

## Controls implemented

- Approved or accepted resource state and exact revision checks before posting.
- Rehearsal-derived SHA-256 fingerprint and resource-bound idempotency key.
- Open, rehearsal-enabled fiscal-period validation.
- Balanced journal rows, stock ledger rows, and party subledger rows in one operational transaction.
- Row locking for source documents, stock positions, reservations, and allocation claims.
- Consumption of stock reservations and allocation claims only with successful posting.
- Immutable counter-batch reversal with inverted journal, stock, and subledger entries.
- Exact stock-revision checks that reject reversal after later stock activity.
- Location-scope authorization and separate `posting.execute` / `posting.reverse` permissions.
- Global `ASAS_POSTING_ENABLED` gate remains the final fail-closed control.

## Verification

- Automated suite: 123 passed, 1 optional PostgreSQL integration test skipped.
- Focused integration tests cover every new resource family, idempotent replay, transfer restoration, payment subledger reversal, and failed-post rollback.
- Docker services rebuilt and healthy at `http://127.0.0.1:18082/`.
- Runtime health reports posting disabled, HR/payroll disabled, authentication enabled, and both databases reachable.
- Operational schema migrations: 14.
- Preserved operational data: 579 stock positions and 264 opening party balances.
- Posting ledger counts after deployment: 0 batches, 0 journal lines, 0 stock entries, and 0 subledger entries.

## Activation status

Production is not activated. Enabling posting requires explicit approval, production security/deployment completion, and setting `ASAS_POSTING_ENABLED=true` in the approved environment. The final BizModo recapture and reconciliation remains a later cutover step.
