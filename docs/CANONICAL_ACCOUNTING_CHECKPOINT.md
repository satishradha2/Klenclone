# Canonical accounting checkpoint

## Result

The accounting evidence has been promoted into canonical, migration-locked target tables for snapshot `bizmodo-2026-09-08-browser`. The process used only the local evidence database and made no connection or change to live BizModo.

| Accounting layer | Source | Target | Variance |
|---|---:|---:|---:|
| GL accounts | 22 | 22 | 0 |
| Journal blueprints | 8,325 | 8,325 | 0 |
| Journal lines | 20,658 | 20,658 | 0 |
| Party subledger controls | 881 | 881 | 0 |
| VAT evidence entries | 4,056 | 4,056 | 0 |
| Cash/bank evidence entries | 4,470 | 4,470 | 0 |
| Trial-balance evidence rows | 532 | 532 | 0 |

## Journal controls

- 8,303 journals are mathematically balanced and `migration_locked_balanced`.
- Eight remain `review_required_source_logic`.
- Fourteen zero-value blueprints remain `review_required_zero_value`.
- Every journal line resolves to one of the 22 provisional GL accounts.
- `approval_enabled=false` and `posting_enabled=false` for every journal.

Balanced means debit equals credit in the blueprint. It is not business approval and does not create a ledger posting.

## Receivables and payables

All 881 parties have a separate subledger control. Of these, 613 contain no due/return balance evidence and 268 contain non-zero balances requiring reconciliation.

| Source control | Gross due | Return due | Net due |
|---|---:|---:|---:|
| Customers | AED 62,630.84 | AED 858.44 | AED 61,772.40 |
| Suppliers | AED 31,670.66 | AED 1,130.85 | AED 30,539.81 |

These values are preserved as current source due controls. They have not been mislabeled or posted as opening balances.

## VAT, cash and trial balance

- VAT: 4,052 entries link deterministically to canonical documents; four remain relationship reviews.
- Cash/bank: 4,466 entries link to canonical accounts/payment evidence; four remain relationship reviews.
- Trial balance: 486 rows retain source labels; 46 rows remain missing-label reviews.
- Tax numbers are reduced to presence indicators in accounting evidence where disclosure is unnecessary; the captured confidential values remain in source/master evidence.

## Financial activation gates

All nine gates are blocked and activation is disabled:

| Gate | Issues |
|---|---:|
| Chart of accounts approval | 22 |
| Journal logic review | 8 |
| Zero-value journal review | 14 |
| Tax linkage | 4 |
| Cash/payment linkage | 4 |
| Trial-balance labels | 46 |
| Accounting reconciliation controls | 8 |
| AR/AP party reconciliation | 268 |
| Opening-balance approval | 1,206 |

## Verification

- Every listed source layer has exact one-to-one target count coverage; all variances are zero.
- A repeated `ledger` build created zero records.
- No GL account, journal, subledger, VAT entry, cash entry or trial-balance row is posting-enabled.
- No activation gate is enabled.
- `python -m pytest -q` passes 35 tests, and compilation succeeds.

This checkpoint is not financial acceptance or cutover approval. All gates require controlled resolution and business sign-off, followed by frozen-source delta extraction and reconciliation because the browser snapshot is non-atomic.
