# Purchase-return atomic posting checkpoint — 2026-09-19

## Outcome

The Asas ERP purchase-return workflow now carries an approved supplier debit
note from controlled stock reservation through a persisted, balanced rehearsal
and the shared atomic posting/reversal engine. The BizModo source remains
read-only. The deployed preview retains the global posting gate, so no permanent
stock, accounting or payable entry is created without separate activation.

## Required linkage and duplicate prevention

- A return must resolve to exactly one posted operational supplier invoice.
- A purchase-invoice source resolves directly by invoice key or supplier invoice
  number. A goods-receipt source resolves through its purchase-order reference.
- Returned supplier quantities must exist on the posted invoice.
- A submitted, approved or posted supplier credit adjustment for the same
  invoice item blocks the return rehearsal.
- Supplier-credit creation also checks returns linked indirectly through goods
  receipts for the same purchase order.

## Persisted non-posting rehearsal

Schema register `0029` adds a revision-bound purchase-return rehearsal record.
It stores the original supplier-invoice revision, fiscal period, journal,
inventory movements, exact reversal plan and deterministic posting fingerprint.
Replaying the same approved revision returns the same idempotency key.

The rehearsal posts no data. Its accounting projection is:

- debit `2100` Trade payables for the supplier recovery;
- credit `1320` Input VAT recoverable;
- credit `1300` Inventory at captured weighted-average cost;
- debit `5120` Inventory write-off for internally discarded quantity; and
- debit or credit `5110` Purchase price variance when supplier recovery differs
  from inventory cost.

The payable subledger credit is tied to the original supplier invoice rather
than treated as an unrelated debit-note balance.

## Atomic execution and reversal

When the separately governed global posting gate is eventually activated, the
shared engine writes the journal, inventory movement, payable subledger and
reservation consumption in one database transaction. The purchase-return maker
cannot execute posting. Idempotent replay cannot create a second batch.

Reversal creates an immutable counter-batch and restores the exact stock state.
It is refused after later stock activity or a later supplier-payment allocation
against the linked invoice. No original batch or audit event is overwritten.

## User interface

The Purchase returns workspace now displays rehearsal and posted counts, the
linked supplier invoice, and controlled Build rehearsal, Post return and Reverse
posting actions. Permanent actions appear only when the global gate and the
corresponding permission are both active.

## Verification

- Focused purchase-return, posting-integration and duplicate-control tests cover
  persistent idempotent rehearsal, maker separation, account codes, invoice-tied
  subledger entries, payment dependency and exact reversal.
- JavaScript syntax is checked before deployment.
- The preview must report posting disabled and zero purchase-return posting
  batches before production approval.
