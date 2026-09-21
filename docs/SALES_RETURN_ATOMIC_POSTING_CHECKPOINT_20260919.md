# Sales-return atomic posting checkpoint — 2026-09-19

## Outcome

The Asas ERP sales-return workflow now preserves immutable evidence from the
selected customer invoice, prevents duplicate or excessive customer credits,
persists its balanced rehearsal, and integrates with the shared atomic posting
and exact-reversal engine. BizModo remains strictly read-only and the deployed
preview retains the global posting lock.

## Original-invoice evidence

When a return is prepared, the clone verifies the selected customer, invoice,
product, UOM, invoiced quantity and unit price against the sealed cloned sales
register. The operational return stores the source-record identity, invoice
total, per-item quantity and price snapshots, and a deterministic SHA-256
evidence hash. A user cannot substitute a different return price.

At submission, the system sums every other submitted, approved or posted return
for the same customer invoice. Both total credit value and per-SKU returned
quantity must remain within the original invoice evidence.

## Persisted non-posting rehearsal

Schema register `0030` adds a revision-bound sales-return rehearsal table and
the immutable invoice-evidence fields. The rehearsal stores its fiscal period,
journal, inventory movements, exact reversal plan and deterministic posting
fingerprint. Replaying the same approved revision returns the same idempotency
key without creating another record.

The balanced accounting projection uses governed account codes:

- debit `4010` Sales returns and discounts;
- debit `2120` Output VAT payable;
- credit `1200` Trade receivables;
- debit `1300` Inventory for saleable returned units;
- debit `5120` Inventory write-off for non-saleable units; and
- credit `5000` Cost of goods sold for the captured original cost.

The receivable subledger credit is tied to the original customer invoice.

## Atomic execution and reversal

After separate activation, journal lines, inventory movements, receivable
subledger credit and document states are committed in one transaction. The
return maker cannot execute posting, and the idempotency key prevents duplicate
batches.

Reversal writes an immutable counter-batch and restores the exact prior stock
state. It is refused after later stock activity or a later customer-receipt
allocation against the original invoice.

## User interface and verification

The Sales returns workspace now shows rehearsal and posting counts, the evidence
hash, and controlled Build rehearsal, Post return and Reverse posting actions.
Permanent actions appear only when the global gate and user permission are both
active. Automated tests cover evidence enforcement, cumulative credit caps,
persisted idempotent rehearsal, maker separation, account codes, invoice-linked
subledger entries, receipt dependencies and exact reversal.
