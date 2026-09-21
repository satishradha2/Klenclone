# Bank and cash reconciliation checkpoint — 19 September 2026

## Outcome

The target Asas ERP now has a controlled bank and cash management workspace. It replaces free-text-only cash/bank handling with approved account masters and adds balanced statement import, receipt/payment matching, explained exceptions, independent reconciliation approval, and a persistent non-posting reconciliation rehearsal.

BizModo remains read-only. No deployment action creates bank accounts, imports statements, posts journals, or changes source evidence.

## Bank and cash account control

1. An authorised maker requests a bank or cash account with its operational code, name, AED GL account, location and business reason.
2. A different authorised approver approves or rejects it. Self-approval is blocked.
3. Only an active bank account can receive a statement import.
4. Once active account masters exist, new receipts and supplier payments must use an approved account for their operational location or the MAIN company scope.
5. Full bank identifiers are not retained by this module; only the final four characters are stored and displayed.

## Statement and reconciliation control

- CSV imports require a source filename, statement reference, period, opening balance, closing balance and transaction lines.
- Required columns are `external_id`, `transaction_date`, `description`, `debit_amount`, and `credit_amount`; `value_date` and `reference` are optional.
- Each line must contain either one debit or one credit and must fall inside the statement period.
- The batch is accepted only when opening balance plus credits minus debits equals the closing balance.
- A deterministic source checksum and account/reference uniqueness prevent duplicate imports.
- Approved customer receipts are eligible for credit-line matching; approved supplier payments are eligible for debit-line matching.
- Suggestions require the approved payment account, direction, amount and date to agree. A payment cannot be matched twice.
- Unmatched lines must be explained as bank fee, bank interest, timing difference, bank error, or another documented exception.
- Every line must be matched or explained before the reconciliation can be submitted.
- A different authorised user must approve or reject the reconciliation.

## Non-posting rehearsal

An approved reconciliation can create an idempotent, fingerprinted rehearsal. It records match and exception counts and proposes balanced adjustment lines for bank fees and bank interest. Timing differences and bank errors remain evidence-only exceptions. The rehearsal never posts a journal and always reports `posting_enabled: false` and `posting_performed: false`.

## Permissions

- `cash.account.prepare`
- `cash.account.approve`
- `bank.statement.import`
- `bank.reconcile.prepare`
- `bank.reconcile.approve`
- `bank.reconcile.rehearse`

All mutations require an authenticated user, the assigned permission, CSRF validation, and location scope.

## Verification

- Focused bank/cash, payment, API, migration and security tests: **18 passed**.
- Full regression: **201 passed, 1 skipped**.
- Python compilation and JavaScript syntax checks passed.
- Operational schema revision is **0038**.
- Permanent posting remains disabled.

All records created during subsequent browser UAT are test data and must be removed with the complete target-ERP test-data purge before the final full BizModo import.
