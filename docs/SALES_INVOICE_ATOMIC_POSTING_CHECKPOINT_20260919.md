# Sales-invoice atomic posting checkpoint — 2026-09-19

## Outcome

The Asas ERP sales-invoice workflow now converts an approved operational sale
into a revision-bound, balanced posting rehearsal and is integrated with the
shared atomic posting and exact-reversal engine. BizModo remains strictly
read-only and the deployed preview retains the global posting lock.

## Stock and document controls

An invoice rehearsal is allowed only for an approved sale in an open,
rehearsal-enabled fiscal period. Every line must have an active reservation for
the same product, location and approved revision, the reservation must cover the
full invoice quantity, and a positive captured cost basis is required.

Schema register `0031` adds a revision-bound sales-invoice rehearsal table. The
record stores its fiscal period, journal, outgoing inventory movements, exact
reversal plan and deterministic posting fingerprint. Replaying the same
approved revision returns the same idempotency key without inserting a second
rehearsal.

## Balanced accounting projection

The non-posting rehearsal uses governed account codes:

- debit `1200` Trade receivables for the gross customer balance;
- credit `4000` Sales revenue for the net value;
- credit `2120` Output VAT payable;
- debit `5000` Cost of goods sold for the captured stock cost; and
- credit `1300` Inventory for the same cost.

The receivable subledger debit is linked to the operational invoice number.

## Atomic execution and reversal

After separate activation, the journal, outgoing stock movements, reservation
consumption, receivable subledger entry and invoice state are committed in one
transaction. The invoice maker cannot execute posting, and the rehearsal
fingerprint prevents duplicate posting batches.

Reversal writes an immutable counter-batch, restores the exact prior stock and
reservation state, and reverses the receivable entry. It is refused after later
stock activity or a later customer-receipt allocation against the invoice.

## User interface and verification

The Draft entry workspace now presents controlled sales invoices and drafts,
stock-reservation and rehearsal counts, and Build rehearsal, Post invoice and
Reverse posting actions. Permanent actions appear only when the global gate and
user permission are both active. Automated tests cover stock prerequisites,
balanced account codes, persistent idempotency, maker separation, atomic
stock/journal/subledger execution, receipt dependencies and exact reversal.
