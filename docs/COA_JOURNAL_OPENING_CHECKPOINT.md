# Provisional COA, journal and inventory-opening checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Status: Non-posting migration blueprint

## Chart of accounts

The provisional chart contains 22 accounts:

- 12 source payment accounts, each assigned a deterministic provisional cash/bank code.
- Accounts Receivable and Accounts Payable controls.
- Inventory and Purchase Clearing.
- Input VAT Recoverable and Output VAT Payable.
- Sales Revenue and Sales Returns.
- Cost of Goods Sold and Operating Expenses.
- A disabled Opening Balance Control account.

Every account has `posting_enabled = false`. The mapping is a migration blueprint and requires business/accountant approval before ERP activation.

## Journal blueprint

| Journal source | Count |
|---|---:|
| Sale invoices | 3,567 |
| Purchase invoices | 446 |
| Sale returns | 38 |
| Purchase returns | 9 |
| Cash-flow settlements | 4,060 |
| Internal transfers | 205 |
| Total | 8,325 |

- 8,303 journals have equal debit and credit totals.
- 14 linked sales-payment events have zero source value and are retained as `zero_value` without artificial lines.
- Eight purchase invoices remain `review_required` because no deterministic input-tax evidence is available.
- No unbalanced journal was generated.
- The blueprint contains 20,658 journal lines, all disabled for posting.

For returned sales, the original positive invoice total comes from its timestamp-matched tax document. The separate return evidence produces the credit-note reversal. This prevents the source list page's return-reduced current total from replacing the original invoice journal.

The eight review-only purchases are `PO2026/0037`, `PO2026/0133`, `PO2026/0134`, `PO2026/0227`, `PO2026/0233`, `PO2026/0432`, `PO2026/0433` and `PO2026/0454`.

## Inventory opening controls

The control schedule compares each closing stock row with supported posted movements using:

`implied opening quantity = closing quantity - net supported movement`

This produces 1,206 product/location controls:

| Status | Controls |
|---|---:|
| Implied opening calculated; approval required | 1,178 |
| Blocked by unresolved movement conversion/product | 17 |
| Blocked by negative closing stock | 4 |
| Blocked by missing stock location | 2 |
| Blocked by unresolved product master | 1 |
| Movement exists without a closing-balance row | 4 |
| Total | 1,206 |

The 28 blocked controls remain non-posting. The 1,178 calculated openings also remain non-posting because they are mathematical implications from a non-atomic 2026 movement window, not an exported and approved opening-stock ledger.

## Posting gate

Nothing in this phase posts to BizModo or to a production ERP. Activation requires:

- business approval of the provisional COA and account classifications;
- source evidence for the eight review-only purchase journals;
- resolution or approved treatment for 28 blocked inventory controls;
- a frozen final export and rerun of all reconciliation stages;
- balanced and approved GL, AR, AP, VAT and inventory opening schedules.

The next implementation phase is the target ERP foundation: organization/location masters, immutable source-key registry, fiscal periods, document numbering, approvals, audit logging and migration-batch controls. HRM is included as an operational module; payroll remains excluded.
