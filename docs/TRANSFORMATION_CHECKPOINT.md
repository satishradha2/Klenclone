# Typed transformation checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Source mode: Browser-only and non-atomic

## Typed rows created

| Table/domain | Rows |
|---|---:|
| Customers and suppliers | 881 |
| Products | 464 |
| Sales headers | 3,567 |
| Purchase headers | 446 |
| Sales and purchase payments | 4,066 |
| Sales and purchase returns | 47 |
| Stock balances | 1,202 |
| Stock-transfer headers | 916 |
| Return and stock-transfer form/detail rows | 4,308 |

The 4,308 detail rows contain 4,219 stock-transfer lines, 44 sales-return lines and 45 purchase-return form rows. Eleven purchase-return rows have a positive returned quantity. Their AED 2,647.00 pre-tax subtotal plus 5% VAT equals the AED 2,779.35 purchase-return header total exactly. Zero-quantity rows remain preserved because they were visible in the source forms.

## Financial parsing controls

- Sales-header total: AED 424,561.20.
- Earlier sales-header paid total: AED 362,108.63.
- Later sales-payment ledger: AED 362,482.13; snapshot drift AED 373.50 remains visible.
- Purchase total: AED 530,187.06.
- Purchase due: AED 31,670.66.
- Purchase-payment ledger: AED 498,516.40; purchase total less due reconciles exactly.
- Sales-return total: AED 2,979.6498, retained at source precision.
- Purchase-return total: AED 2,779.35.

## Automated integrity exceptions

| Control | Result |
|---|---:|
| Duplicate sales references | 1 reference / 2 rows |
| Duplicate purchase references | 1 reference / 2 rows |
| Negative stock | 4 rows |
| Stock without location | 3 rows |
| Orphan payments | 0 |
| Orphan returns | 0 |
| Later detail without earlier header | `ST2026/0927` |

There are ten open reconciliation exceptions: two duplicate-reference exceptions, four negative-stock exceptions, three missing-location exceptions and one live-snapshot transfer exception.

## Safety and repeatability

- Every typed row retains `snapshot_id` and `raw_record_id` provenance.
- Currency and quantity fields use decimal storage, not binary floating point.
- Dates are parsed in the source `Asia/Dubai` timezone.
- Running the transform twice produced identical counts.
- Typed tables are rebuilt in one local staging transaction; immutable raw evidence is never edited.

## Next checkpoint

Resolve master-data identities and relationships: link transaction contact names to customer/supplier IDs, map SKU and UOM references, join payments/returns to immutable transaction IDs, and produce per-document header-to-line reconciliation before generating operational ERP records.
