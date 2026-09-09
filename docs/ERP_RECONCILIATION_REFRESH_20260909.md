# ERP reconciliation refresh — 2026-09-09

> **RETRACTED — cross-project target.** The source reconciliation remains evidence, but the staging/posting sections used the separate `D:\Klen+ ERP` project and are not completion evidence for the BizModo clone. See `docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md`.

## Decision summary

The earlier −171-unit provisional stock correction has been replaced by a fresh, location-level capture. Current stock now reconciles exactly between the BizModo stock report and product register: **29,124.02 base units across 470 SKUs, with zero SKU differences**.

The source remained active throughout capture. This package is therefore a controlled timestamped refresh, not an atomic final cutover.

## Dataset and grain

Source evidence is sealed by SHA-256 in `var/erp_reconciliation_refreshes/20260909T101320Z/package/PACKAGE_STATUS.json`.

| Dataset | Grain | Rows |
| --- | --- | ---: |
| Stock report | SKU × BizModo location | 1,211 |
| Product register | SKU | 470 |
| Customer register | Contact ID | 794 |
| Supplier register | Contact ID | 88 |
| Sales headers | Invoice | 3,591 |
| Purchase headers | Purchase | 450 |
| Sales returns | Return | 39 |
| Purchase returns | Return | 9 |
| Customer/supplier YTD report | Contact display name | 508 |

## Findings

### Stock — passed, high confidence

- Location report quantity: 29,124.02.
- Product-register quantity: 29,124.02.
- SKU differences: 0 of 470.
- Positive opening rows: 579, totaling 29,137.02.
- Genuine negative stock: four rows totaling −13.00.
- Two missing-location rows both have zero quantity and do not affect valuation or quantity.
- Five products were added after the prior capture: 98084, 98085, 98086, 98087, and 98088.

The five product masters have been posted to operational staging. Negative stock is preserved in a dedicated migration-exception ledger; it is not discarded, converted to a positive opening amount, or allowed to weaken the ERP's non-negative inventory constraint.

### Negative-stock safety design

- Migration `0088_negative_stock_migration_exceptions.sql` creates an auditable exception ledger for source-negative SKU/location balances.
- The `opening_stock_adjustments` import accepts only signed negative quantities and posts them to that ledger rather than operational inventory.
- The four source exceptions total −13.00 units and retain their source SKU, location, quantity, cost, reason, and resolution status.
- Operational staging currently contains zero posted migration inventory exceptions; the behavior was proved only in the isolated rehearsal database.

### Partner balances — source-key complete, non-atomic

| Control | Positive balance | Advances/contra | Net position |
| --- | ---: | ---: | ---: |
| Customers | AED 62,680.16 | AED 681.86 across 9 contacts | AED 61,998.30 receivable |
| Suppliers | AED 31,665.00 | AED 133.04 across 6 contacts | AED 31,531.96 payable |

Customer and supplier Contact IDs are used as the authoritative migration keys. Negative customer balances are classified as customer advances; negative supplier balances are classified as supplier advances. The advance package contains 30 balanced GL lines representing 15 partner-level journals.

### Secondary-report differences — high risk for invoice-level ageing

- Sales-header due less sales-return due: AED 63,890.51 versus customer-master net AED 61,998.30; variance −AED 1,892.21.
- Purchase-header due less purchase-return due: AED 31,983.71 versus supplier-master net AED 31,531.96; variance −AED 451.75.
- YTD customer/supplier signed due: AED 31,221.05 versus contact-master customer-minus-supplier net AED 30,466.34.

Likely causes are activity occurring between sequential browser exports, different report treatment of payments/returns, and header-versus-contact balance semantics. These differences do not prevent a contact-level opening balance, but they do prevent a claim of exact invoice-level ageing and payment allocation.

## Automated controls

- Every source and package file is SHA-256 bound.
- Product SKU uniqueness and stock SKU coverage are checked.
- Stock location totals must equal product-register totals.
- Positive opening stock and negative source adjustments are separated.
- Negative migration adjustments must be strictly below zero.
- Partner advances are generated as balanced two-line journals.
- All product, partner, account, warehouse, and location references were checked against an isolated ERP database.
- Package validation result: 867 of 867 rows valid; zero errors and zero duplicates; the isolated transaction was rolled back and business-table counts remained unchanged.
- A separate isolated post-and-rollback rehearsal posted all five financial and stock batches with zero reconciliation difference.
- Post-rehearsal controls were AED 62,680.16 AR, AED 31,665.00 AP, AED 814.90 advance debits and credits, 29,137.02 positive stock, and −13.00 quarantined negative stock, producing the exact source net of 29,124.02.
- Rollback restored the original invoice, journal, migration-exception, and net inventory controls. Compensating inventory movements and zero-balance rows remained as designed for auditability.
- Klen Clone automated suite: 79 passed, 1 skipped.

## Operational staging state

- Backup before staging: `var/erp_reconciliation_refreshes/20260909T101320Z/pre-refresh-staging.dump`
- Backup SHA-256: `F5B9AFA57F37F05A307BBC9FCDB7C493F6D909440BDBF9E44CF9BC883B72C8AD`
- Operational report: `var/erp_reconciliation_refreshes/20260909T101320Z/operational-staging-report.json`
- Operational report SHA-256: `710B40B0FEEC057244B80FE9B7443E716258C37D6BFD1481F2AA14657FE301DE`
- Product batch `RREF-20260909-1031-1`: posted, five rows.
- Batches `RREF-20260909-1031-2` through `-6`: posted in operational staging with zero reconciliation difference.
- Operational posting report: `var/erp_reconciliation_refreshes/20260909T101320Z/operational-post-report.json`
- Operational posting report SHA-256: `EA3BC6F1906525821F9C31D30378E7B4F9358851F95ABAB364717542BE92701D`
- Post totals are AED 62,680.16 receivables, AED 31,665.00 payables, AED 814.90 balanced advance debits/credits, 29,137.02 positive stock, and −13.00 quarantined negative stock.
- After posting, operational staging contains 590 stock movements, 583 inventory balances, 204 customer invoices, 53 supplier invoices, 268 journal entries, and four migration inventory exceptions.
- Staging backend readiness: ready; signed stock-adjustment validation is active.
- Migration 0088 is applied in staging, and its four exception-ledger rows reconcile to −13.00 units.

## Isolated posting evidence

- Report: `var/erp_reconciliation_refreshes/20260909T101320Z/isolated-post-rollback-report.json`
- Report SHA-256: `FFFFB46C0D2042F7736F6A2A7D8365FA5A34AD9C7795D712C45406122462F967`
- Rehearsal database: `klen_erp_reconciliation_refresh_20260909_101320` (disposable clone of operational staging).
- All batches `RREF-20260909-1031-2` through `-6` posted successfully in isolation and reconciled to their source controls.
- The isolated rehearsal was rolled back; it did not post financial or stock openings into operational staging.

## Remaining gate

The operational-staging posting gate has passed. The backend readiness endpoint is healthy and every stored source-versus-posted reconciliation difference is zero. The local ERP frontend also renders successfully; authenticated balance-page acceptance remains subject to an OrbisHub staging session.

The next step is functional acceptance of the staged opening balances, followed by a final small BizModo delta immediately before cutover (or a transaction pause during the last capture). Production remains unchanged and must not be opened for use until that cutover delta is reconciled and a recoverable production backup exists.
