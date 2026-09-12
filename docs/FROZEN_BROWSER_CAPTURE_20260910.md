# Frozen browser capture — 2026-09-10

Status: **zero observable drift; staging delta prepared; production remains disabled**

## Outcome

BizModo V7.5.1 was accessed with the authenticated browser after the agreed post-midnight freeze. All actions were read-only. The opening and closing watermark comparison passed across ten tracked streams with no changed count or latest source reference.

The immutable browser package is in `source_exports/2026-09-10-frozen-browser-cutover`. It contains ten full or overlapping register extracts, opening and closing watermarks, file hashes and a 142-row deduplicated staging delta.

To protect the remaining capture opportunity, consolidated detail controls were also preserved: 576 sales-product lines for the current BizModo business day, 12 purchase-product lines dated 09 September 2026, and 1,222 current SKU/location stock rows. Their checksums are included in the package manifest.

## Captured registers

| Register | Scope | Rows | Latest evidence |
| --- | --- | ---: | --- |
| Sales | 12 Aug–10 Sep 2026 overlap | 1,041 | `AK2026-03667` |
| Purchases | 2026 | 458 | `PO2026/0467` |
| Products | Full visible register | 474 | Count control |
| Customers | Full visible register | 795 | Count control |
| Suppliers | Full visible register | 91 | Count control |
| Stock transfers | 2026 | 937 | `ST2026/0947` |
| Sales payments | 2026 | 3,714 | `SP2026/3826` |
| Purchase payments | 2026 | 417 | `PP2026/0446` |
| Sales returns | 2026 | 41 | `CN2026/0043` |
| Purchase returns | 2026 | 10 | `2026/0013` |

## New records versus the preserved prior package

The source-ID comparison found 142 new register rows: 9 products, 1 customer, 3 suppliers, 11 purchases, 44 sales, 17 stock transfers, 49 sales payments, 4 purchase payments, 3 sales returns and 1 purchase return. Every previous ID remains present in each full-scope register. Sales is the exception because the current file is an explicit 30-day overlap; 44 source invoice IDs are new relative to the prior full-year sales file.

BizModo continues to expose duplicate source references `PO2026/0339` and `AK2026-03080`. The full extracts preserve both rows. The staging delta excludes these old IDs and records them as reconciliation exceptions.

## Controls and limitations

- The opening/closing comparison reports `stable_watermarks`, no changed streams and `final_capture_allowed=true` for the observable browser window.
- The annual sales filter returned an impossible zero twice. A 30-day overlap containing 1,041 rows was captured instead and deduplicated by invoice ID against the prior 3,584-row package.
- A later quick sales refresh again returned an impossible zero, so it is retained as a source-report defect rather than interpreted as activity or deletion. The earlier completed opening/closing pair remains the accepted zero-drift control.
- Browser register tables do not guarantee hidden database fields, deleted records, transaction lines or uploaded documents.
- The delta files are staging inputs only. No operational or canonical business table was modified.
- HRM/payroll remains excluded.
- Production merge and posting remain disabled.

## Next gate

Load the 142-row delta into a disposable staging database, link transaction details, reconcile stock, AR/AP, VAT and control accounts, and reject any unresolved duplicate or missing relationship. Only an explicitly approved production cutover may follow that rehearsal.
