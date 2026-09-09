# Goods Receipts Foundation Checkpoint — 2026-09-09

## Delivered

- Separate GRN workflow; supplier invoices are not treated as proof of physical receipt.
- Draft create/edit with optimistic revision control and location-scoped access.
- Ordered, received, accepted and rejected quantities with conservation controls.
- Mandatory rejection reason, plus batch and expiry traceability.
- Maker-checker submit and independent accept/reject workflow.
- Posting rehearsal limited to accepted base quantity and accepted value.
- Balanced Inventory debit / GRNI credit rehearsal with deterministic fingerprint.

## Safety state

- Permanent posting remains disabled by application and database controls.
- No stock position or accounting ledger is changed by a GRN or rehearsal.
- BizModo remains read-only and is never called by this operational workflow.
- Existing operational data is preserved; schema revision is `0009`.

## Verification

- JavaScript syntax validation passed.
- Full automated suite: 98 passed, 1 intentionally skipped.
- Production activation is not authorized by this checkpoint.
