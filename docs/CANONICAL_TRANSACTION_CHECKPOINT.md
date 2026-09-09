# Canonical transaction checkpoint

## Result

Sales, purchases, returns, stock transfers, transaction lines, payments and inventory movements have been promoted into migration-locked canonical tables for snapshot `bizmodo-2026-09-08-browser`. This operation used only the confidential local evidence database and did not connect to or change BizModo.

| Transaction layer | Source | Target | Variance |
|---|---:|---:|---:|
| Documents | 4,976 | 4,976 | 0 |
| Lines | 13,837 | 13,837 | 0 |
| Payments | 4,066 | 4,066 | 0 |
| Inventory movements | 18,022 | 18,022 | 0 |

Documents comprise 3,567 sales, 446 purchases, 47 returns and 916 stock transfers. Lines comprise 8,466 sales lines, 1,063 purchase lines and 4,308 captured return/transfer detail lines.

## Migration readiness

| Record type | Migration-locked ready | Review required |
|---|---:|---:|
| Documents | 4,948 | 28 financial controls |
| Lines | 13,815 | 22 parent/product relationships |
| Payments | 4,063 | 3 ambiguous parent relationships |
| Inventory movements | 17,982 | 15 source-header + 25 UOM conversion reviews |

“Migration-locked ready” means the captured record has sufficient deterministic evidence for a future controlled load. It does not mean approved, operational or posted.

## Exception queue

The target exception queue contains 188 activation-blocking items. It combines canonical transaction checks with existing reconciliation findings:

- 22 transaction-line relationship exceptions.
- Three payment-parent relationship exceptions.
- 40 inventory-movement readiness exceptions.
- 28 financial-allocation review exceptions.
- 95 existing reconciliation exceptions retained individually with their original code, severity, entity and evidence.

Standalone purchase returns previously classified as `not_applicable` remain valid standalone documents; they are not falsely treated as broken parent links.

## Quantity and document controls

- Entered quantity and entered UOM are preserved separately.
- `factor_to_base_snapshot` and `quantity_base` are retained from the controlled inventory reconstruction.
- Source document number and source typed/raw IDs remain attached to every target record.
- Document totals, paid/due values and source statuses are evidence fields.
- A BizModo `posted` status is stored only as `source_posting_status`; target `posting_enabled` remains false.
- No missing parent, product, location or UOM conversion is fabricated.

## Verification

- Every source document, line, payment and reconstructed movement has exactly one target record; all four count variances are zero.
- A repeated `transactions` run created zero records.
- All target transaction and inventory posting flags are false.
- `python -m pytest -q` passes 33 tests, and compilation succeeds.

This checkpoint is not cutover approval. Review queues must be resolved or formally approved, and the final migration still requires transaction-free repeat exports and delta reconciliation because the browser evidence is not atomic.
