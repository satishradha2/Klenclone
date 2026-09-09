# Isolated delta dry-run checkpoint

Source evidence date: 2026-09-09  
Execution ID (UTC): `20260908T223256Z`  
Status: **passed**

## Outcome

The three checksum-verified UI delta packages were transformed into a new disposable SQLite validation database:

`var/delta_dry_runs/20260908T223256Z/delta_validation.db`

Database SHA-256:

`BB87942BAB0784DDDC3F056F240BE530FDC267115A5903B4C870C1720CAB22ED`

The dry-run executed 30 controls: 30 passed and zero failed. The database metadata explicitly records `validation_only=true`, `posting_enabled=false`, `promotion_allowed=false`, and `opening_gl_allowed=false`.

## Transformed rows

| Entity | Rows |
| --- | ---: |
| Customers | 1 |
| Products | 1 |
| Purchases | 1 |
| Sales | 15 |
| Sale-line evidence | 35 |
| Sale-detail payment evidence | 8 |
| Sales-payment register rows | 12 |
| Output-VAT rows | 12 |
| Cash-flow rows | 12 |

Raw UI strings and the structured values are retained together. Nothing from the dry-run is promoted into canonical ERP, PostgreSQL, opening balances, or operational posting tables.

## Passed controls

- Every source JSON file matched `SHA256SUMS.txt` before and after processing.
- All three packages remained marked non-atomic and non-mutating.
- Invoice keys are exactly the 15 unique values `AK2026-03607` through `AK2026-03621`.
- All 15 sale equations satisfy payable = paid + remaining.
- Sale totals reconcile to AED 1,784.75 payable, AED 591.00 paid, and AED 1,193.75 remaining.
- The 8 sale-detail receipts match the 8 new-sale payment-register references totaling AED 591.00.
- The other 4 payment-register rows relate to earlier sales and total AED 343.50.
- All 12 payment references match 12 cash-flow entries; credit is AED 934.50 and debit is zero.
- The 12 output-VAT rows are exactly `AK2026-03610` through `AK2026-03621` and total AED 62.81.
- Customer `CO0892`, product `98081`, purchase `PO2026/0456`, and transfer `ST2026/0927` relationships are internally consistent.
- The purchase reconciles as AED 61.90 net plus AED 3.10 VAT equals AED 65.00 and remains unpaid.
- One carton of SKU `98081` is evidenced at DXB after the completed transfer.
- The trial-balance evidence remains blocked and was not promoted to opening GL balances.

## Safety behavior

The transformer refuses to overwrite an existing output and refuses protected database names including `klen_staging.db` and the former UAT databases. A checksum mismatch aborts before a database is created. A failed control produces a validation-only result and a non-zero CLI exit status.

The preserved PostgreSQL clone remained healthy in `migration_read_only` mode with posting disabled. Port 18082 remained closed; UAT was not restarted. BizModo was not accessed or changed during this local dry-run.

## Verification

- Focused delta tests: 3 passed.
- Complete local suite: 61 passed, 1 PostgreSQL-environment test skipped.
- Independent SQLite inspection confirmed all row counts, 30 passing validations, zero failures, and both posting and promotion disabled.

## Remaining gate

This proves that the captured UI delta is internally transformable, not that it is a complete or atomic source snapshot. Promotion into the preserved clone remains blocked until controlled full exports are obtained at a transaction-free cutoff and reconciled against these records.
