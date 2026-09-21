# Procurement tolerance and supplier-adjustment checkpoint

Date: 2026-09-15

## Outcome

The target ERP now supports a governed three-way-match price tolerance and controlled supplier credit/debit notes linked to approved supplier invoices.

The active match policy defaults to zero tolerance. A Finance Controller may propose a percentage and absolute line-amount tolerance, but a different Chief Financial Officer must approve or reject that change. A price difference within the active tolerance is never treated as an automatic match: it creates a recorded tolerance-review exception that requires a separately authorized approval before the normal supplier-invoice approval can proceed.

The following remain hard failures and cannot be cleared through price tolerance:

- supplier or currency mismatch;
- missing or insufficient independently accepted receipt quantity;
- invoice quantity above the ordered or accepted quantity;
- VAT-rate mismatch;
- missing PO, receipt, invoice, or item linkage.

Accounts Payable can prepare credit or debit notes only against an approved supplier invoice. Each adjustment retains its original invoice-line linkage, supplier, location, currency, tax calculation, reason, maker, status, and audit timestamps. A different Finance Approver must approve a submitted adjustment. Cumulative active credit-note quantity cannot exceed the quantity on the original invoice; debit notes remain explicit additions rather than silently changing the invoice.

## Posting boundary

Tolerance approvals and supplier adjustments are workflow records only. They do not create inventory movements, payables, VAT postings, journal entries, payments, or reversals. `posting_enabled` remains false.

All records in this checkpoint are target-ERP test data. BizModo remains strictly read-only. At final cutover, all target test data will be deleted before a fresh full BizModo extraction and import under an authorized cutover runbook.

## Remaining gates

- complete final supplier-master TRN review against the fresh source capture; invoice-level tax-document validation is implemented in `SUPPLIER_TAX_AND_POSTING_REHEARSAL_CHECKPOINT_20260915.md`;
- design, approve, and test production postings for inventory, GRNI, AP, VAT, adjustments, and reversals;
- execute named-user and location-scoped UAT;
- perform the destructive test-data purge and final full import only under the separately authorized cutover procedure.
