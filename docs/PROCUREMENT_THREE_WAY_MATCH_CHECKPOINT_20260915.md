# Procurement three-way match checkpoint

Date: 2026-09-15

## Outcome

The target ERP now joins the governed procurement documents that were previously separate:

`Approved purchase order -> goods receipt and inspection -> supplier invoice -> independent approval`

An approved PO number can be entered as the Goods Receipts purchase reference. The ERP then requires the receipt supplier, location, SKU, UOM, cost, and cumulative quantity to agree with that PO. Partial receipts are permitted; over-receipt is blocked.

Accounts Payable can capture an AED supplier invoice against an approved PO and run a three-way match. The match checks:

- supplier and currency inherited from the PO;
- invoice SKU and cumulative quantity against the PO;
- invoice quantity against independently accepted receipt quantity;
- unit price against the awarded PO price;
- VAT rate against the PO line;
- duplicate supplier invoice references;
- user location scope.

Exceptions are recorded with item-specific reasons. An exception invoice cannot be approved. A passed match requires an independent user with `supplier_bill.approve`; the invoice maker cannot approve their own invoice.

## Posting boundary

All records created here are target-ERP test data. Approved receipts and invoices do not create inventory movements, GRNI, trade payables, input VAT, ledger journals, or payments. `posting_enabled` remains false throughout.

BizModo remains read-only and no source evidence is altered. Before final cutover, all target operational test rows will be deleted and the final fresh source capture will be imported under a separately authorized runbook.

## Remaining gates

- tax-document validation beyond the captured invoice and adjustment VAT controls;
- production quantity-tolerance policy, if the business elects to allow one (over-receipt and invoice quantities above accepted stock remain hard failures);
- production posting for inventory, GRNI, AP, VAT, and reversals;
- final named-user/location UAT and cutover acceptance.
