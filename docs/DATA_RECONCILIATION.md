# Data reconciliation checkpoint

Checkpoint date: 2026-09-08 (Asia/Dubai)

This checkpoint uses read-only UI navigation and exports. No source record was created, edited, approved, cancelled, deleted, imported, assigned, or reconfigured.

## Readiness conclusion

The captured evidence is suitable for inventory discovery and staging design, but it is not yet safe as a final migration snapshot. The source is actively changing, UI exports are non-atomic, and several financial and stock controls have unresolved variances.

## Transaction grains

| Control | Result | Status |
|---|---:|---|
| Sales headers | 3,567 rows / 3,566 distinct invoice numbers | Duplicate legacy invoice found |
| Sales product lines | 8,466 rows / 3,569 distinct invoice references | Annual count reconciled; captured later than headers |
| POS headers | 3,394 rows / 3,394 distinct invoice numbers | All keys existed in the earlier all-sales snapshot |
| Purchase headers | 446 rows / 445 distinct purchase numbers | Duplicate legacy purchase number found |
| Purchase product lines | 1,063 rows / 445 distinct purchase references | Reference set reconciled |
| Sales payments | 3,653 rows / AED 362,482.13 | Later snapshot than sales headers |
| Purchase payments | 413 rows / AED 498,516.40 | Reconciles to purchase total less footer due |
| Item traceability | 5,560 rows | Purchase-to-sale allocation evidence captured |
| Stock by location | 1,202 rows | Four negative and three unlocated rows |
| Cash flow | 4,470 rows | Partition total equals annual UI control |
| Input tax | 448 rows / AED 24,907.69 VAT | Captured |
| Output tax | 3,608 rows / AED 20,247.93 VAT | Captured |
| Trial balance | 24 visible accounts | Out of balance by AED 41,042.55 |
| Sales-return details | 38 headers / 44 product lines | Captured from all view dialogs |
| Purchase-return details | 9 headers / 41 visible product rows | Captured without saving five parent and four standalone forms |
| Stock-transfer details | 917 headers / 4,219 product lines | Later snapshot; one more header than the earlier CSV |

## Financial controls

| Control | Left side | Right side | Variance |
|---|---:|---:|---:|
| Customer receivables | Customer master AED 62,630.84 | Sales due AED 63,342.75 less return due AED 858.44 = AED 62,484.31 | AED 146.53 |
| Supplier payable row sum | Purchase footer/master AED 31,670.66 | Purchase-row due sum AED 31,665.66 | AED 5.00 |
| Purchase payments | Purchases AED 530,187.06 less due AED 31,670.66 | Payment ledger AED 498,516.40 | AED 0.00 |
| Sales paid snapshot | Later payment ledger AED 362,482.13 | Earlier header paid total AED 362,108.63 | AED 373.50 snapshot drift |
| Sales line-to-header | Line total AED 425,026.93 | Header total AED 418,266.99 | AED 6,759.94 pending adjustment allocation |
| Purchase line-to-header | Line subtotal AED 504,395.60 | Header total AED 530,187.06 | AED 25,791.46 pending tax/freight/discount allocation |
| Trial balance | Debit AED 861,430.28 | Credit AED 820,387.73 | AED 41,042.55 |
| Balance sheet | Assets AED 169,212.25 | Liabilities and owners' capital AED 59,294.19 | AED 109,918.06 |
| Profit calculation | Product gross profit AED 72,727.73 | Top-level gross profit AED 58,826.75 | AED 13,900.98 scope difference |

## Annual financial report evidence

- Profit/loss: sales excluding tax AED 404,768.25; sales including tax AED 425,026.44; weighted-average COGS AED 332,745.79; FIFO COGS AED 332,026.56; gross profit AED 58,826.75; net profit AED 58,857.66.
- Tax: input VAT AED 24,907.69; output VAT AED 20,247.93; expense-tax rows zero. The source renders the overall result as `-4846.753799999999 AED` rather than a currency-rounded decimal.
- Cash flow: eight disjoint primary files contain 4,470 rows, exactly matching the annual UI count. Diagnostic boundary files overlap the primary files and are excluded from staging.
- Accounting: the trial balance and balance sheet fail their fundamental equality controls and cannot be accepted as opening ERP balances.

## Sales-detail extraction proof

BizModo showed 8,466 annual product-sale rows. Monthly exports returned only noon on the first day through 11:59 AM on the last day even though the controls displayed `12:00 AM` and `11:59 PM`.

- Month files: 8,192 business rows.
- Five half-day boundary files: 274 business rows.
- Controlled union: 8,466 rows.
- Annual UI control: 8,466 rows.
- Variance: zero.
- Duplicate full rows in the controlled union: zero.

The boundary files are evidence, not replacement data. Staging must union them with the month files, retain provenance, and deduplicate only by an agreed immutable line key.

## Required gates before migration import

1. Obtain an atomic database/server backup or establish a transaction-free cutover window.
2. Re-run tax, cash-flow, profit/loss, trial balance and balance sheet at the final frozen cutoff.
3. Reconcile the captured return and stock-transfer details to a frozen final snapshot; obtain uploaded-file storage because no attachment links were exposed.
4. Resolve duplicate document numbers without deleting either source row.
5. Reconcile every header to lines, payments, returns, tax, rounding, freight and inventory movements.
6. Approve negative and unlocated stock exceptions.

Raw files remain unchanged under `source_exports/2026-09-08/` and are excluded from version control.

The first local staging import preserves 41,444 raw records from 86 supported files. Re-importing the unchanged directory is idempotent, and both known duplicate document numbers are raised as reconciliation exceptions. See `IMPORT_CHECKPOINT.md`.

Typed staging now contains 881 parties, 464 products, 3,567 sales, 446 purchases, 4,066 payments, 47 returns, 1,202 stock balances, 916 transfer headers and 4,308 return/transfer detail rows. Automated relationship checks found zero orphan payments and zero orphan returns, while preserving `ST2026/0927` as later-detail snapshot drift. See `TRANSFORMATION_CHECKPOINT.md`.

Identity resolution produced 51,971 deterministic links, five ambiguous links and four valid standalone-return outcomes. All sales/purchase line product and contact links resolved; exact unique product-name fallback resolved return details that lacked SKUs. Preliminary controls identified 480 documents requiring adjustment breakdown. VAT, discount, controlled rounding, returns, payments and due allocations subsequently reconciled 3,985 of 4,013 headers, leaving 28 controlled documents. See `RELATIONSHIP_RECONCILIATION.md` and `FINANCIAL_ALLOCATION_CHECKPOINT.md`.

Accounting staging now preserves 4,470 primary cash-flow rows, 12 payment accounts and 532 trial-balance rows. All 205 internal fund transfers pair exactly. Cash-flow net movement reconciles to the final per-account balances, while six cross-source controls remain materially out of balance and two payment controls are explained by ten payment-ledger rows absent from cash flow. See `ACCOUNTING_LEDGER_CHECKPOINT.md`.

A 22-account provisional COA and 8,325 non-posting journal blueprints have been generated. Of these, 8,303 balance exactly, 14 are zero-value source events and eight purchase invoices remain review-only because tax evidence is absent. Inventory controls calculate 1,178 implied openings while blocking 28 product/location controls from posting. See `COA_JOURNAL_OPENING_CHECKPOINT.md`.

## Browser-only detail checkpoint

- Sales returns: 38 of 38 detail views captured, containing 44 product lines and activity history.
- Purchase returns: 9 of 9 forms captured, containing 41 visible product rows. No Save or Update control was used.
- Stock transfers: 917 of 917 later detail views captured, containing 4,219 product lines and activity history.
- Purchases: all 447 later detail views scanned for attachment/download links. None were exposed. Two payment notes refer to an attached voucher without providing a link.
- Sales: 2,300 of 3,572 later detail views completed the attachment-link scan before repeated browser-session limits. No attachment/download links were exposed in the verified subset; the remaining 1,272 are not claimed as scanned.
