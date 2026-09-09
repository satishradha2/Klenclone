# Identity and document reconciliation checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Source status: Non-atomic browser snapshot

## Resolution outcome

The resolver created 52,002 typed relationship decisions:

- 51,971 resolved deterministically.
- 5 ambiguous: three payments point to duplicated legacy document numbers and two return lines have duplicated exact product-name candidates.
- 4 marked not applicable because they are legitimate standalone purchase returns without a parent purchase.
- 22 unmatched: 11 sale lines belong to three sales created after the earlier header export, nine return-detail product names lack an exact unique master match, one stock row is for the later SKU `98081`, and one transfer detail belongs to a header created after the earlier export.

## High-confidence links

| Relationship | Resolved | Ambiguous | Unmatched |
|---|---:|---:|---:|
| Sales lines to sales | 8,455 | 0 | 11 |
| Sales lines to products | 8,466 | 0 | 0 |
| Sales lines to customers | 8,466 | 0 | 0 |
| Purchase lines to purchases | 1,063 | 0 | 0 |
| Purchase lines to products | 1,063 | 0 | 0 |
| Purchase lines to suppliers | 1,063 | 0 | 0 |
| Sales headers to customers | 3,567 | 0 | 0 |
| Purchase headers to suppliers | 446 | 0 | 0 |
| Item traceability to products | 5,560 | 0 | 0 |
| Stock balances to products | 1,201 | 0 | 1 |
| Return/transfer detail lines to products | 4,297 | 2 | 9 |
| Transfer lines to transfer headers | 4,218 | 0 | 1 |

Sales use exact `Contact ID` from line evidence before normalized-name fallback. Purchase identity uses document number, date, supplier and exact normalized supplier names. Product identity uses exact SKU first; detail rows without an SKU may use an exact, unique normalized product name. No fuzzy match is promoted automatically.

## Ambiguous payments

| Payment | Parent document | Amount | Cause |
|---|---|---:|---|
| `PP2026/0346` | `PO2026/0339` | AED 231.00 | Two purchase headers use the same document number |
| `PP2026/0340` | `PO2026/0339` | AED 195.00 | Two purchase headers use the same document number |
| `SP2026/3240` | `AK2026-03080` | AED 83.00 | Two sales headers use the same invoice number |

These payments remain unallocated. Resolving them requires an immutable source transaction ID, reliable timestamp linkage, or business confirmation.

## Live-snapshot drift

- Eleven lines totaling AED 465.25 belong to later sales `AK2026-03607`, `AK2026-03608` and `AK2026-03609`; those headers were created after the earlier sales export.
- SKU `98081`, Clear Tape 100 yard (1x36pcs), appears in later stock/transfer evidence but not in the earlier product master.
- Transfer `ST2026/0927` appears in later detail evidence but not the earlier transfer-header CSV.

These are retained as critical snapshot-drift exceptions, not treated as corrupt rows.

## Per-document reconciliation

| Document type | Balanced | Requires adjustment breakdown |
|---|---:|---:|
| Sales | 3,521 | 46 |
| Purchases | 12 | 434 |
| Total | 3,533 | 480 |

- Resolved sales header-to-line variance totals AED -0.48, indicating only small aggregate rounding/adjustment differences after excluding the three later sales.
- Purchase header-to-line variance totals AED 25,791.46 because purchase-line exports are before document-level tax, freight and discounts.
- Purchase settlement variance is AED 426.00, exactly the two ambiguous purchase payments above.
- Sales settlement variance is AED -1,180.68 and remains open for return/payment timing and allocation analysis.

## Exception queue

Nineteen relationship, snapshot and stock exceptions are currently open before UOM controls:

- 2 duplicate document-number exceptions.
- 5 ambiguous relationship exceptions.
- 4 detail/header snapshot-drift exceptions.
- 1 product-master snapshot-drift exception.
- 4 negative-stock exceptions.
- 3 missing-location exceptions.

Canonical UOM and inventory-movement reconstruction is recorded in `INVENTORY_UOM_CHECKPOINT.md`. Financial allocation subsequently reduced the 480-document preliminary adjustment population to 28 controlled documents; see `FINANCIAL_ALLOCATION_CHECKPOINT.md`.

## 2026-09-09 evidence addendum

Read-only live detail capture identified product master SKU `98081`, purchase `PO2026/0456`, and completed transfer `ST2026/0927`. The product view reports one carton at DXB, while the transfer evidence records one carton moving from Asas General Trading LLC to DXB. This closes the evidentiary relationship between the previously unmatched stock row and transfer detail.

The original 52,002 baseline resolver decisions and exception counts above remain unchanged because the new UI package is non-atomic and has not been imported. The supporting record is `source_exports/2026-09-09-ui-delta/master_purchase_details.json`; a controlled export and rerun of the resolver are still required before those baseline exceptions may be formally reclassified.
