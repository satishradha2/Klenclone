# Isolated delta merge simulation checkpoint

Source evidence date: 2026-09-09  
Execution ID (UTC): `20260908T223753Z`  
Status: **passed with one blocker**

## Outcome

The preserved SQLite clone was opened read-only and copied with SQLite's backup mechanism to:

`var/delta_merge_simulations/20260908T223753Z/merge_simulation.db`

Simulation database SHA-256:

`7F9A58F2194F080677BBA182F7BCB3B52325EF2D1C118EC2B9ABB4921561B777`

Only `delta_merge_*` planning and control tables were added to the disposable copy. No row was inserted, updated, or deleted in any pre-existing business table. The preserved clone and validated delta database retained their pre-run hashes.

## Merge plan

| Action | Rows |
| --- | ---: |
| Insert | 82 |
| Reuse existing | 12 |
| Update | 0 |
| Conflict | 1 |
| Total | 95 |

The 12 reuse decisions prevent duplication of 11 sale lines already captured for invoices `AK2026-03607` through `AK2026-03609` and the existing `ST2026/0927` transfer-detail line.

## Projected staging counts

| Table | Before | Planned inserts | Projected after | Actual after simulation |
| --- | ---: | ---: | ---: | ---: |
| `stg_contacts` | 881 | 1 | 882 | 881 |
| `stg_products` | 464 | 1 | 465 | 464 |
| `stg_purchases` | 446 | 1 | 447 | 446 |
| `stg_purchase_lines` | 1,063 | 1 | 1,064 | 1,063 |
| `stg_sales` | 3,567 | 15 | 3,582 | 3,567 |
| `stg_sale_lines` | 8,466 | 24 | 8,490 | 8,466 |
| `stg_payments` | 4,066 | 12 | 4,078 | 4,066 |
| `stg_tax_evidence` | 4,056 | 12 | 4,068 | 4,056 |
| `stg_cash_flow_entries` | 4,470 | 12 | 4,482 | 4,470 |
| `stg_stock_transfers` | 916 | 1 | 917 | 916 |
| `stg_stock_balances` | 1,202 | 2 | 1,204 | 1,202 |

Actual counts remain unchanged because this is a plan-only simulation.

## Blocking conflict

The clone already contains an unlocated zero-quantity stock row for SKU `98081`, while the later product view shows two location-specific rows: zero cartons at Asas General Trading LLC and one carton at DXB after transfer `ST2026/0927`.

The simulator refuses to replace, delete, or silently duplicate the unlocated row. `merge_allowed=false` remains enforced until a controlled full stock export establishes the authoritative location balance and the unlocated evidence is explicitly reconciled.

## Safety and verification

- Posting is disabled.
- Merge execution is disabled.
- Existing output files and protected database names are refused.
- The source clone is read using SQLite `mode=ro` and `PRAGMA query_only=ON`.
- The validated delta database is also opened read-only.
- Existing business-table counts are compared before and after plan creation.
- Focused simulation tests: 2 passed.
- Complete test suite: 63 passed, 1 PostgreSQL-environment test skipped.
- PostgreSQL validation service remained healthy and non-posting on port 18081.
- Port 18082 remained closed; UAT was not restarted.

## Remaining gate

No real merge is authorized. The next safe step is to obtain a fresh full-location stock export, reconcile SKU `98081`, and rerun this simulation. Final promotion still requires a transaction-free cutover capture or a source database and uploaded-file backup.

## Resolution addendum

This historical blocker was resolved on 2026-09-09 using the checksum-protected BizModo stock-report export. The rerun produced 82 inserts, 13 safe reuses, zero updates, and zero conflicts while retaining the unlocated zero-quantity row unchanged as legacy evidence. See `STOCK_LOCATION_RECONCILIATION_CHECKPOINT.md`.
