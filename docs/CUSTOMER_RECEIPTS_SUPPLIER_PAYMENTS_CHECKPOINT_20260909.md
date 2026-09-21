# Customer Receipts and Supplier Payments Checkpoint — 2026-09-09

## Delivered scope

The independent Asas ERP now includes controlled customer-receipt and supplier-payment workflows. A payment can be allocated across cloned open invoices and approved operational opening balances, while any unapplied amount is explicitly retained as a customer or supplier advance.

## Controls implemented

- Separate `customer_receipt` and `supplier_payment` document types with their own numbering.
- Cloned customer/supplier and location validation; location-level authorization is enforced.
- Server-authoritative invoice and opening-balance outstanding amounts.
- Allocation amounts cannot exceed the payment or the selected source outstanding.
- Invoice-level and opening-balance allocations share the approved party opening control, so they cannot be double-counted as separate balances.
- Duplicate source allocations within one payment are rejected.
- Submitted allocations create operational claims. Matching source rows are locked before claim totals are checked, preventing concurrent pending payments from over-allocating the same balance.
- Cancellation releases active allocation claims.
- Draft-only editing with optimistic revision checks.
- Independent maker-checker approval.
- Bank, card and cheque methods require an external reference.
- Payment-date fiscal-period validation before rehearsal.
- Append-only workflow and audit evidence.

## Rehearsal accounting

Customer receipt:

- Debit cash/bank for the full receipt.
- Credit Accounts Receivable for allocated value.
- Credit Customer Advances for unapplied value.

Supplier payment:

- Debit Accounts Payable for allocated value.
- Debit Supplier Advances for unapplied value.
- Credit cash/bank for the full payment.

The API also produces invoice/opening-balance subledger allocation plans, deterministic fingerprints and idempotency keys. These are rehearsal artefacts only.

## Safety state

- BizModo is not called or modified by this workflow.
- The immutable clone remains the source evidence.
- Permanent posting is database-constrained off.
- No payment, allocation, claim, journal or subledger rows are created during deployment.
- Operational schema revision is `0013`.
- HRM is included in the target ERP; payroll remains excluded.

## Verification

- Payment module tests cover receipt allocation, advances, supplier payments, maker-checker, allocation claims, cancellation release, revision protection, fiscal locks and invalid totals.
- Full automated suite: 115 passed; one optional PostgreSQL integration test skipped when its dedicated test URL is not configured.
- JavaScript syntax validation passed for the payment workspace.

## Next enterprise increment

Build AR/AP ageing and accounting reports from the immutable cloned balances plus operational allocation claims. Reports must distinguish source outstanding, reserved allocation, approved-but-unposted activity, advances and future posted balances.
