# ERP master import rehearsal checkpoint

> **RETRACTED — cross-project target.** This checkpoint used the separate `D:\Klen+ ERP` staging schema and is not completion evidence for the BizModo clone. See `docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md`.

Date: 2026-09-09  
Decision: proceed incrementally with currently accessible BizModo data; capture and reconcile later deltas without overwriting source-linked records.

## Scope completed

The validated non-atomic register package was transformed into ERP migration templates using stable source keys:

| Master | Source key | Prepared | Validated | Errors | Duplicates |
|---|---|---:|---:|---:|---:|
| Products | SKU | 465 | 465 | 0 | 0 |
| Customers | Contact ID | 794 | 794 | 0 | 0 |
| Suppliers | Contact ID | 88 | 88 | 0 | 0 |
| **Total** |  | **1,347** | **1,347** | **0** | **0** |

The package is `var/erp_import_rehearsals/20260909T081310Z/package`. It is checksum-bound and explicitly carries `posting_enabled=false` and `promotion_allowed=false`.

## Safe transformations

- Product base UOM codes were derived from the visible source base-stock unit without inventing conversion factors.
- Source payment terms were mapped to COD or an explicit NET-days code.
- Four customers without a business name use the preserved contact name as a reversible staging fallback.
- Invalid or duplicate UAE TRNs were not discarded or silently accepted. Their source values remain in the immutable capture; the ERP field is blank in the rehearsal template and the condition is recorded in `exceptions.json` using the source key and a value hash.
- The package contains 48 transformation exceptions requiring later data stewardship.

## Database rehearsal

An isolated PostgreSQL database named `klen_erp_import_rehearsal_20260909_081310` was created and migrated through schema `0087`. Three migration batches containing 1,347 rows passed the ERP's own validation rules with zero errors and zero duplicates.

No isolated business tables were populated: products, partners, stock movements, customer invoices and supplier invoices all remained at zero.

## Operational staging placement

Before changing the running ERP staging database, a recoverable PostgreSQL custom-format backup was created:

- `var/erp_import_rehearsals/20260909T081310Z/pre-import-staging.dump`
- SHA-256: `B11889A59C34F389A15D429664A9138E682794A46CFB2FECDE7BDA23B56DD382`

The same three batches were then added to the operational staging migration workspace and left in `validated` status:

- Products: 465 valid, 0 errors, 0 duplicates
- Customers: 794 valid, 0 errors, 0 duplicates
- Suppliers: 88 valid, 0 errors, 0 duplicates
- Rehearsal rows posted: 0

Business-table counts were identical before and after the operation. The staging API remained ready.

Validation report:

- `var/erp_import_rehearsals/20260909T081310Z/operational-staging-validation.json`
- SHA-256: `63751C5F822630A70E9E2AF079C0C472F01FD42617170FA593E7EA72F718C24F`

## Deliberately deferred

- Opening stock: current location-level stock was not available in the non-atomic register capture.
- Historical sales and purchases: headers are preserved, but transaction lines are incomplete and were not invented.
- Receivables: 708 positive-due candidates totaling AED 64,066.25 are deferred. Only 7 currently match a unique customer name; 701 require a stronger source-key mapping.
- Payables: 174 positive-due candidates totaling AED 31,732.72 are deferred because supplier names do not yet resolve reliably to supplier source keys.
- Attachments and hidden source fields remain pending.

## Control status

This checkpoint authorizes continued staged reconciliation only. It does not authorize submit, approval, posting, stock activation, opening balances, or production use. Later source captures must upsert by SKU or Contact ID and produce an explicit changed/new/conflict plan before promotion.

## Staging master promotion

Following explicit authorization to proceed with the currently available data, the three clean batches were promoted into the local ERP staging business tables as a technical staging migration. This is not production approval or business UAT.

A second recoverable backup was created immediately before promotion:

- `var/erp_import_rehearsals/20260909T081310Z/pre-promotion-staging.dump`
- SHA-256: `C871488E9122DA76C31F12B0EC62D402C29A5D15AF95D0658D0FEE9282615602`

Promotion reconciliation:

| Entity | Source rows | Posted rows | Difference |
|---|---:|---:|---:|
| Products | 465 | 465 | 0 |
| Customers | 794 | 794 | 0 |
| Suppliers | 88 | 88 | 0 |

Business-count deltas were 465 products, 882 partners and 858 partner addresses. Existing product and partner records were preserved. Stock movements, customer invoices and supplier invoices were unchanged, so no opening stock, balance or historical transaction was posted.

The technical maker/poster was the staging System Administrator and the separate checker was the staging Export UAT Checker. These are staging actors only and do not constitute production approval. The ERP readiness endpoint remained ready after promotion.

- Promotion report: `var/erp_import_rehearsals/20260909T081310Z/master-promotion-report.json`
- SHA-256: `04D71517E40A069BC04B73ABF42DF7235B1FF81BFAAD59B441D36827B1F2E2FA`
- Preserved SQLite clone last-write time remained `2026-09-08T19:10:44Z`; live hash recomputation was not attempted after the file was found open by the separate local read-only dashboard process.
