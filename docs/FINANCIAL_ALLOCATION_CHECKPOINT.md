# Financial allocation checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Source status: Non-atomic, read-only browser snapshot

## Outcome

The staging database now contains 4,056 source-faithful tax-evidence rows and 4,013 document-level financial allocations. VAT, discount, rounding, returns, payments and due amounts are stored separately with traceable source IDs and matching methods.

- 4,052 tax rows link deterministically to a sale, purchase or return using document number and local wall-clock timestamp.
- Four later-snapshot tax rows remain unmatched: sales `AK2026-03607`, `AK2026-03608`, `AK2026-03609` and purchase `PO2026/0456`.
- Duplicate legacy numbers `AK2026-03080` and `PO2026/0339` are safely disambiguated by timestamp for tax evidence.
- Negative output-tax reversals are linked to their matching return timestamps rather than to the original sale.

## Allocation result

| Status | Documents |
|---|---:|
| Balanced | 3,985 |
| Settlement residual only | 12 |
| Allocation residual only | 10 |
| Source line gap | 5 |
| Allocation and settlement residual | 1 |
| Total | 4,013 |

The preliminary relationship pass placed 480 documents in adjustment review. Source tax and discount allocation, document-specific VAT semantics, controlled rounding and exact return offsets reduce that population to 28 unique documents.

## Source semantics retained

- Sales product-line totals normally include VAT. One sale also includes its document discount in the exported line total, so the discount is not subtracted twice.
- Purchase product lines normally exclude VAT, but eight early purchases demonstrably include VAT because the unchanged line total exactly equals the header and tax-report total.
- 384 documents contain non-zero sub-currency line aggregation differences of at most AED 0.10; these are recorded as explicit rounding adjustments.
- Thirteen sales returns exactly offset an otherwise non-zero settlement residual and are applied as controlled return offsets.
- Seven settlement differences of at most AED 0.10 are recorded separately as settlement rounding.
- Returns already reflected in paid/due balances are preserved but not applied again.

## Remaining controlled cases

Five purchases have tax-report totals that reconcile exactly to their headers but their exported product lines are short by AED 1,230.00 in total. These are classified as source line gaps, not invented freight or product lines:

| Purchase | Missing line value |
|---|---:|
| `PO2026/0154` | AED 425.00 |
| `PO2026/0243` | AED 370.00 |
| `PO2026/0155` | AED 246.00 |
| `PO2026/0224` | AED 127.00 |
| `PO2026/0078` | AED 62.00 |

Three purchases have header-to-line differences equal to 5% but no corresponding input-tax row in the accessible tax export: `PO2026/0432` AED 22.50, `PO2026/0433` AED 85.00 and `PO2026/0454` AED 79.50. They remain unclassified until source tax evidence or business confirmation is available. Purchase `PO2026/0134` has an unexplained AED -0.13 difference.

Sixteen allocation exceptions and thirteen settlement exceptions remain, with one document in both sets. The two duplicated `PO2026/0339` purchases retain AED 231.00 and AED 195.00 settlement exceptions because their payment records cannot be assigned safely. The duplicated `AK2026-03080` sale similarly retains an AED 83.00 settlement exception.

## Control rule

No balancing journal, tax amount, freight charge or discount is invented. Every adjustment is either copied from tax/payment/return evidence, proven by exact document arithmetic, or retained as a named exception.

Accounting evidence-ledger reconstruction and reconciliation of cash flow, VAT control accounts, AR/AP and trial balance is recorded in `ACCOUNTING_LEDGER_CHECKPOINT.md`. Opening balances remain blocked pending balanced source evidence or formal business approval.
