# Customer Invoice Checkpoint — 2026-09-19

## Implemented boundary

Customer invoices are now created only from a sales order that has completed the controlled fulfilment chain:

`accepted quotation → confirmed sales order → allocation → pick → dispatch / delivery note → proof of delivery → customer invoice`

The delivery must be in `delivered` status and must contain a delivery-note number, receiver name, and POD reference. One fulfilment can create only one invoice. The invoice copies the customer name, sales-order number, delivery-note number, POD reference, delivered quantities, UOM snapshots, prices, discount, VAT, and total from the controlled source records. Commercial lines and quantities are not editable in the invoice checkpoint.

## Workflow controls

- Invoice statuses: `draft`, `submitted`, `approved`, `rejected`, and `cancelled`.
- Invoice creator cannot approve or reject the same invoice.
- Every transition uses optimistic revision checks and an audit event.
- Approval and rejection require a reason.
- Invoice date cannot precede POD; due date cannot precede invoice date.
- Duplicate and excess invoicing are prevented by unique fulfilment and delivery-line constraints.
- Customer-facing tables display the customer name without concatenating the internal customer code.

## Accounting boundary

An approved invoice may run a persistent, fingerprinted, idempotent rehearsal for:

- Debit `1200 Trade receivables`
- Credit `4000 Sales revenue`
- Credit `2120 Output VAT payable`

The rehearsal is balanced and requires an open, rehearsal-enabled fiscal period. It creates no permanent journal or subledger posting. It also creates no stock movement because the physical warehouse issue already occurred exactly once at delivery dispatch. Permanent accounting posting remains disabled.

## Verification

- Focused delivery and customer-invoice tests: `6 passed`.
- Complete regression suite: `186 passed, 1 skipped`.
- Container health endpoint: healthy, operational database reachable, posting disabled.
- Operational migration `0034`: applied.
- Existing POD-backed delivery: one delivered, uninvoiced fulfilment available after deployment.

Browser maker-checker validation requires a fresh sign-in after an ERP container restart because local preview sessions are process-local.
