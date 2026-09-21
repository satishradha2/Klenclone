# Enterprise procurement checkpoint

Date: 2026-09-15

## Outcome

The target Asas ERP now provides a controlled procurement chain:

1. A Procurement Requester creates and submits a location-scoped purchase requisition.
2. A Procurement Manager independently approves or rejects it.
3. A Buyer opens an RFQ for at least two active suppliers.
4. The Buyer captures a complete AED quotation from each invited supplier.
5. The ERP compares every requested item and identifies the lowest unit price.
6. The Buyer records the selected quotation and creates a draft purchase order.
7. The Buyer submits the purchase order and a Procurement Manager independently approves or rejects it.

The award is a controlled commercial decision. Lowest price is highlighted but is not auto-awarded because delivery time, terms, specification compliance, quality, and other documented factors may justify another supplier.

## Controls

- Requisition approval and purchase-order approval are distinct permissions.
- The maker cannot approve or reject their own requisition or purchase order.
- User location scope filters the workspace and protects every document action.
- RFQs require at least two distinct, active suppliers.
- Quotations must cover every requisition SKU exactly once; duplicate SKUs are rejected.
- A quotation validity date cannot precede its quotation date.
- Only AED quotations are enabled until governed exchange-rate controls exist.
- Quantities preserve the product factor snapshot and `quantity_base = quantity x factor_to_base_snapshot`.
- Every workflow transition is audited and revision checked.

## Posting and source protection

Approval does not create inventory, goods receipt, GRNI, accounts payable, ledger, or payment entries. Approved POs can now be referenced by controlled goods receipts and supplier invoices, as recorded in `PROCUREMENT_THREE_WAY_MATCH_CHECKPOINT_20260915.md`, but posting remains disabled.

BizModo remains read-only. Its inventory records zero purchase requisitions and zero purchase orders, so this workspace is a new target-ERP operational capability, not a change to source evidence. Current operational entries are test data and will be fully deleted before the separately authorized final fresh BizModo import.

## Deferred activation gates

- Final business roles, named users, and location assignments
- Supplier qualification and commercial-policy approval
- Foreign-currency and exchange-rate governance
- Production posting, monitoring, backup, and cutover acceptance
