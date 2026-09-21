# Supplier adjustment atomic posting checkpoint

Date: 2026-09-19

## Outcome

Approved supplier credit and debit notes can now enter the same activation-gated atomic posting engine as supplier invoices. The deployed test preview remains non-posting because `ASAS_POSTING_ENABLED` is false.

Each adjustment retains its original supplier-invoice link and requires one explicit accounting treatment:

- `price_variance`: account 5110, Purchase price variance.
- `freight_landed_cost`: account 5100, Freight and landed cost.
- `administrative_expense`: account 6100, Administrative expense.

Goods returns are excluded from this adjustment path. They must use Purchase returns, which controls stock reservation, inventory movement and its own supplier debit note. A credit note is rejected when a submitted, approved or posted purchase return already controls the same original invoice item.

## Accounting behavior

A supplier credit note debits Trade payables and credits Input VAT plus the selected offset account. A supplier debit note debits the selected offset and Input VAT and credits Trade payables. Every plan must balance before it receives a checksum-bound idempotency key.

Permanent execution additionally requires:

- approved adjustment status;
- a posted original supplier invoice;
- independent posting actor, different from the adjustment maker;
- matching approved revision, fingerprint and idempotency key; and
- the global posting activation gate.

Posting creates an immutable journal batch and a signed supplier payable-subledger movement against the original invoice reference. Failure rolls back the complete transaction. Replay returns the existing batch instead of duplicating it.

## Reversal controls

Reversal writes an exact counter-batch; it never edits or deletes the original ledger rows. A later active or consumed supplier-payment allocation against the original invoice blocks adjustment reversal until that dependency is released.

## Schema and validation

- Operational schema register: `0028`.
- Integrated resource type: `supplier_adjustment`.
- Rehearsal endpoint: `POST /api/v1/procurement/supplier-adjustments/{adjustment_key}/posting-rehearsal`.
- Posting endpoint: `POST /api/v1/posting/supplier_adjustment/{adjustment_key}`.
- Reversal uses the common integrated-posting reversal endpoint.
- Automated verification: 171 passed, 1 optional PostgreSQL test skipped.

## Safety boundary

No BizModo record was accessed or modified. Existing ERP records remain test data and must be fully purged before the final fresh BizModo import. No permanent posting was activated or executed in the deployed preview.
