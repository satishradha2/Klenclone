# Accounting evidence-ledger checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Source status: Non-atomic, read-only browser snapshot

## Reconstructed evidence

The staging database now preserves:

- 12 payment-account snapshots.
- 4,470 primary cash-flow entries. Diagnostic boundary exports remain raw evidence and are excluded from the union to prevent duplicates.
- 532 trial-balance export rows, including 46 rows whose account label is blank in the source XLSX XML.
- Nine cross-source accounting controls covering cash, payments, VAT, AR/AP and both trial-balance views.

Cash-flow classification produced 3,649 sale receipts, 407 purchase payments, three purchase-return receipts, one sale-return payment and 410 internal-transfer legs.

## Cash and transfer integrity

- All 410 fund-transfer legs form 205 exact debit/credit pairs by timestamp and amount.
- No internal-transfer row is unpaired.
- No remaining cash-flow sign anomaly exists after purchase-return receipts and zero-value sales-payment records are classified correctly.
- Cash-flow debit totals AED 1,134,439.11 and credit totals AED 1,002,844.33.
- Net cash-flow movement of AED -131,594.78 exactly equals the sum of the final balances for the ten accounts appearing in cash flow.
- The later payment-account snapshot totals AED -131,968.28, a difference of AED -373.50 from cash flow. This remains snapshot drift rather than an opening-balance journal.

## Payment links

- 4,056 cash-flow rows link deterministically to payment records by exact payment reference.
- Four return cash-flow references have no corresponding record in the sale/purchase payment exports: `PP2026/0229`, `PP2026/0361`, `PP2026/0370` and `SP2026/0128`.
- Ten payment-ledger rows are absent from cash flow.

The missing cash-flow rows explain the payment control differences exactly:

| Control | Payment ledger | Cash flow | Explained difference |
|---|---:|---:|---:|
| Sales payments | AED 362,482.13 | AED 362,002.78 | AED 479.35 from four missing cash rows |
| Purchase payments | AED 498,516.40 | AED 495,214.56 | AED 3,301.84 from six missing cash rows |

These controls are classified as explained variances, but the ten missing rows remain row-level cutover exceptions.

## VAT, receivables and payables

| Control | Operational evidence | Trial balance | Variance |
|---|---:|---:|---:|
| Output VAT | AED 20,247.933 | AED 20,340.760 credit | AED -92.827 |
| Net customer AR | AED 61,772.40 | AED 2,551.60 debit | AED 59,220.80 |
| Net supplier AP | AED 30,539.81 | AED 38,953.43 credit | AED -8,413.62 |

Input VAT evidence totals AED 24,907.6868, but the exported trial balance exposes no named Input Tax account. No comparison or guessed account assignment is made.

## Trial-balance defect

Two distinct source controls disagree and both are unbalanced:

| Trial-balance scope | Debit | Credit | Difference |
|---|---:|---:|---:|
| Browser UI, 24 visible top-level accounts | AED 861,430.28 | AED 820,387.73 | AED 41,042.55 |
| All 532 exported parent/detail rows | AED 930,029.02 | AED 862,301.36 | AED 67,727.66 |

The XLSX contains parent and detail rows together and has 46 amount-bearing rows with no account label in its source XML. Therefore neither total is promoted to an ERP opening trial balance.

## Migration gate

One accounting control balances, two payment controls have fully explained variances, and six controls remain unresolved. No balancing journal has been generated. Opening GL, AR, AP, VAT and retained-earnings balances remain blocked until a frozen extract or formally approved opening-balance schedule is available.

The provisional enterprise chart of accounts, balanced journal blueprint and inventory opening controls are recorded in `COA_JOURNAL_OPENING_CHECKPOINT.md`. Every mapping remains non-posting until approved.
