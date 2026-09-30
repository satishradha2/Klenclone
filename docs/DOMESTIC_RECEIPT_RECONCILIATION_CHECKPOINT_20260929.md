# Domestic receipt reconciliation checkpoint — 29 September 2026

Build-stage synthetic tests only. BizModo source remains read-only. This checkpoint is not production acceptance or cutover authorization.

## Corrected

When a receipt is posted, its allocation claim becomes `consumed`. Customer-invoice settlement and receipt-allocation limits now treat both active and consumed claims as obligations, while excluding released claims after reversal. A posted receipt therefore continues reducing the invoice balance and cannot be allocated a second time.

Customer statements and credit exposure include posted receipts. The AR/AP ageing report distinguishes submitted, approved-unposted, and posted allocations and advances, with reporting-date filters on payment dates and target invoice dates. Its table now exposes posted allocations as a separate column.

## Synthetic trace

The test creates a delivery-backed AED 19.95 customer invoice, posts an AED 6.00 partial receipt, verifies AED 13.95 outstanding across settlement, open items, customer statement and credit exposure, rejects a second AED 14.00 allocation, then reverses the receipt and verifies AED 19.95 outstanding again. It checks that a statement dated before the receipt does not include it. Separate ageing tests verify the posted allocation and date cutoff.

## Follow-on status

Target-invoice-linked, discount-aware return credits were added in the subsequent [domestic target-return checkpoint](DOMESTIC_TARGET_RETURN_CHECKPOINT_20260929.md). Historical as-of reports after a later reversal still need event-time ledger reconstruction; the current report cutoff filters current document state and payment date.
