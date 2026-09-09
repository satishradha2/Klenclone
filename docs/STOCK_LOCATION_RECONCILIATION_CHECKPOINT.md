# Stock-location reconciliation checkpoint

Source evidence date: 2026-09-09  
Delta execution ID (UTC): `20260908T224316Z`  
Merge-simulation execution ID (UTC): `20260908T224332Z`  
Status: **reconciled; zero merge-plan conflicts**

## Read-only evidence

The authenticated BizModo V7.5.1 stock report was filtered to SKU `98081` and exported without changing source data. The preserved evidence is:

`source_exports/2026-09-09-ui-delta/stock_report_98081.csv`

SHA-256:

`AAAE974DDAEB372AA6A8B43F1DE9061D80E94508EBEA891E6B3F0B6AB90017ED`

The report contains exactly two current location rows:

| Location | Available | Transferred | Purchase value | Sale value |
| --- | ---: | ---: | ---: | ---: |
| Asas General Trading LLC | 0.00 Carton | 1.00 Carton | AED 0.00 | AED 0.00 |
| DXB | 1.00 Carton | 0.00 Carton | AED 61.90 | AED 81.71 |
| Total | 1.00 Carton | 1.00 Carton | AED 61.90 | AED 81.71 |

This agrees with completed transfer `ST2026/0927`: one carton moved from Asas General Trading LLC to DXB.

## Validated delta

The checksum-protected evidence package was rebuilt into:

`var/delta_dry_runs/20260908T224316Z/delta_validation.db`

SHA-256:

`AA9F40F7C0EE2701D49732C28454148598E4D5514DA5176CAA487A54EB34CCC7`

All 33 controls passed. The database is validation-only, with posting and promotion disabled.

## Isolated merge simulation

The new disposable simulation database is:

`var/delta_merge_simulations/20260908T224332Z/merge_simulation.db`

SHA-256:

`E9D8E349DC79DD6AD966E63731775C5BD139D0988450362C9FB887D44B7336AD`

| Action | Rows |
| --- | ---: |
| Insert | 82 |
| Reuse existing | 13 |
| Update | 0 |
| Conflict | 0 |
| Total | 95 |

The earlier unlocated zero-quantity row for SKU `98081` is retained unchanged as legacy evidence. It is not deleted, relocated, or posted. The two authoritative location rows are planned separately, and their combined quantity equals the product total of one carton.

## Safety and remaining gate

- No pre-existing business table changed during simulation.
- The preserved clone and validated delta retained their pre-run hashes.
- Posting remains disabled and `merge_allowed=false`; this is still a plan-only simulation.
- Complete test suite: 63 passed, 1 PostgreSQL-environment test skipped.
- Port 18082 remains disabled.

The SKU `98081` location blocker is closed. A real merge is still prohibited until a transaction-free cutover capture or source database and uploaded-file backup is available, because username/password UI exports cannot guarantee an atomic no-data-loss migration.
