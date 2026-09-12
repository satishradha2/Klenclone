# Frozen browser delta staging checkpoint — 2026-09-10

## Outcome

- Immutable capture: `source_exports/2026-09-10-frozen-browser-cutover`
- Integrity: 31 manifest entries verified; 0 missing or mismatched files
- Disposable database: `var/frozen_browser_delta_staging/20260910T042046/browser_delta_staging.db`
- Header/register delta rows preserved: 142
- Production merge allowed: false
- Posting enabled: false
- Source mutation: false

## Detail evidence staged

- Sales product lines linked to the new sales: 116
- Purchase product lines linked to the new purchases: 14
- Stock-by-location rows: 1,222
- Stock-transfer documents: 17 of 17
- Sales-return documents: 3 of 3
- Purchase-return documents: 1 of 1
- Supplemental purchase-detail documents: 2

## Resolved reconciliation exception

Purchase line-level evidence for `PO2026/0460` and `PO2026/0465` was captured
through read-only View dialogs and stored as checksum-protected supplemental
evidence. All 11 new purchase headers now have line-level coverage. The staging
run reports zero exceptions and zero failed checks.

## Verification

- Automated suite: 132 passed, 1 optional PostgreSQL test skipped
- Operational integrated posting rows: batches 0, journal lines 0, stock
  entries 0, subledger entries 0
- Docker ERP preview and operational database remained healthy

## Gate

This checkpoint is validation-only. It is not approval to activate production,
post accounting/stock movements, or merge the frozen delta into operational
tables.
