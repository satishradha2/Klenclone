# Expense and petty-cash checkpoint — 21 September 2026

## Result

The target Asas ERP now includes an operational expense and petty-cash workspace. It is isolated from the protected BizModo evidence and creates no permanent accounting postings.

## Expense controls

- Claims capture claimant, date, location, cost centre, approved category, description and receipt reference.
- Source category evidence is retained for Cost of Goods Sold, Cost of sales and Fuel; controlled target categories add bank charges, office administration and travel.
- Direct-payment and petty-cash claims require an active approved bank/cash account in the same location.
- Reimbursements credit an employee-reimbursement payable in rehearsal instead of pretending cash was already paid.
- VAT is restricted to 0% or 5%. A 5% claim must calculate exactly and requires a tax-invoice reference plus a 15-digit supplier TRN before submission.
- Maker-checker control prevents the creator from deciding the claim. Revision checks and decision notes are mandatory.

## Petty-cash controls

- Advances require an active approved cash account, recipient, purpose, cost centre, request date and settlement due date.
- Independent approval is required before issue.
- Settlement requires `spent + returned = issued amount` exactly.
- Any spent amount requires an approved category and receipt reference.
- Open and overdue advances are counted separately for follow-up.

## Accounting rehearsals

- Approved expenses create a balanced, fingerprinted rehearsal for expense, eligible Input VAT and the selected cash/bank account or reimbursement payable.
- Petty-cash issue rehearsals debit Employee Advances and credit the approved cash account.
- Petty-cash settlement rehearsals debit the expense and returned cash, then credit Employee Advances.
- Rehearsals are idempotent per revision and always report `posting_enabled: false` and `posting_performed: false`.

## Permissions

- `expense.prepare`
- `expense.submit`
- `expense.approve`
- `expense.rehearse`
- `petty_cash.prepare`
- `petty_cash.approve`
- `petty_cash.manage`

Maker permissions are added to the provisioned operations-administrator role and decision permissions to the finance-approver role. Location scope remains enforced.

## Test-data boundary

All records created during UAT are target-ERP testing records and will be deleted before the final fresh BizModo import. No BizModo source record is updated or deleted by this checkpoint.
