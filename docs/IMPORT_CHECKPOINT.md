# Staging import checkpoint

Checkpoint: 2026-09-08, Asia/Dubai  
Snapshot: `bizmodo-2026-09-08-browser`  
Atomic source snapshot: No

## Result

- 86 supported CSV, JSON and XLSX files imported.
- 41,444 raw records preserved with file, ordinal, SHA-256 and source snapshot provenance.
- 42 presentation/header/footer rows retained and marked for quarantine; none were deleted.
- A second import of the identical directory imported zero records and safely skipped all 86 unchanged files.
- The importer rejects a changed file when its snapshot name and relative path already exist.
- The malformed-style trial-balance workbook was read through a read-only XLSX XML fallback. It contains 532 exported account/detail rows after its header, while the UI checkpoint showed 24 visible top-level accounts.

## Key business-row controls

| Entity | Staging count | Expected evidence count | Result |
|---|---:|---:|---|
| Customers | 793 | 793 | Match |
| Suppliers | 88 | 88 | Match |
| Products | 464 | 464 | Match; contaminated bulk-action row quarantined |
| Sales | 3,567 | 3,567 | Match |
| POS sales | 3,394 | 3,394 | Match |
| Purchases | 446 | 446 | Match |
| Sales returns | 38 | 38 | Match |
| Purchase returns | 9 | 9 | Match |
| Sales payments | 3,653 | 3,653 | Match |
| Purchase payments | 413 | 413 | Match |
| Sales line primary partitions | 8,192 | 8,192 | Match |
| Sales line boundary supplements | 274 | 274 | Match |
| Purchase lines | 1,063 | 1,063 | Match |
| Item traceability | 5,560 | 5,560 | Match |
| Stock balances | 1,202 | 1,202 | Match |
| Stock transfer headers | 916 | 916 | Match earlier CSV |
| Stock transfer details | 917 | 917 | Match later detail snapshot; live drift retained |
| Cash-flow primary partitions | 4,470 | 4,470 | Match |
| Input tax | 448 | 448 | Match |
| Output tax | 3,608 | 3,608 | Match |

## Automatically raised exceptions

- Duplicate sales number `AK2026-03080`: two source rows preserved.
- Duplicate purchase number `PO2026/0339`: two source rows preserved.
- Snapshot remains non-atomic and cannot be promoted directly to final opening balances.

## Next engineering checkpoint

Build typed canonical staging transforms for parties, products/UOM, sales, purchases, returns, payments and inventory. Each transform must retain the raw-record foreign key and emit reconciliation exceptions instead of silently repairing source defects.
