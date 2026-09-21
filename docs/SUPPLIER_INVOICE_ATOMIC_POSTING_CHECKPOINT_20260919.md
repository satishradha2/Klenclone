# Supplier invoice atomic posting checkpoint

Date: 2026-09-19

## Outcome

Approved, three-way-matched supplier invoices now use the ERP's common atomic posting engine. The implementation remains behind the global `ASAS_POSTING_ENABLED` activation control, so the deployed test preview continues to reject permanent posting with HTTP 503.

When that gate is separately approved and enabled, a supplier-invoice posting creates one indivisible accounting transaction:

- Debit Goods received not invoiced (GRNI) for the invoice net amount.
- Debit Input VAT recoverable for validated VAT.
- Credit Trade payables for the gross amount.
- Create the matching supplier payable subledger entry.
- Mark the approved invoice posted only after all ledger rows succeed.

Any failure rolls back the whole transaction. The rehearsal fingerprint and idempotency key must match the approved invoice revision, and replaying the same key returns the original batch without duplicating entries. The invoice maker cannot execute its posting.

## Reversal controls

Reversal creates a new immutable counter-batch with exact opposite journal and payable-subledger amounts. It does not edit or delete the original batch. Reversal is refused when:

- a linked supplier-payment allocation is active or consumed; or
- later supplier credit/debit-note activity is still draft, submitted or approved.

Cancelled or rejected dependent activity no longer blocks the controlled reversal. The original posting batch and invoice are marked reversed only after the complete counter-batch succeeds.

## Schema and interface

- Operational schema register: `0027`.
- Integrated resource type: `supplier_invoice`.
- Posting endpoint: `POST /api/v1/posting/supplier_invoice/{invoice_key}`.
- Reversal endpoint: `POST /api/v1/integrated-posting-batches/{batch_key}/reverse`.
- The procurement workspace exposes posting or reversal actions only when the global posting gate is active and the signed-in user has the corresponding permission.

## Safety boundary

This checkpoint changes only the target ERP code and target operational schema. It does not access or alter BizModo. The existing test data remains test-only and must be fully purged before the separately controlled final full BizModo import. No production posting activation is granted by this checkpoint.
