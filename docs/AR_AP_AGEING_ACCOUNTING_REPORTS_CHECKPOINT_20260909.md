# AR/AP Ageing and Accounting Reports Checkpoint — 2026-09-09

## Delivered scope

The independent Asas ERP now provides permission-protected receivable and payable ageing plus an accounting evidence summary. The reporting layer combines the immutable BizModo invoice evidence with the approved operational opening balances and non-posting payment-allocation pipeline without changing or posting any record.

## Ageing method

- The approved opening receivable/payable balance is the authoritative party control.
- Submitted and approved-but-unposted allocations are shown separately and reduce the control outstanding.
- Invoice evidence is aged independently and never silently substituted for the opening control.
- Reliable contractual due dates were not available in the captured source, so buckets use invoice date and the UI discloses that basis.
- Buckets are 0–30, 31–60, 61–90, 91+ and undated days.
- Source advances, submitted advances and approved-but-unposted advances are reported separately.
- Net exposure is the remaining opening control less all disclosed advances.
- The difference between control outstanding and aged invoice evidence is visible for every party.

## Authorization

- Access requires `financial_report.read`.
- Company-wide location scope is required because the migrated opening AR/AP balances are party-level and not location-distributed.
- A partial-location user is rejected rather than receiving a misleading partial report.

## Accounting evidence summary

The Accounting workspace now shows:

- preserved trial-balance debit, credit and difference;
- cloned journal-blueprint totals;
- classified cash evidence;
- VAT evidence;
- approved opening AR/AP controls; and
- the operational payment pipeline, separately identified as unposted.

## Deployed snapshot results

As at 2026-09-09:

- Receivable report: 210 parties, AED 62,680.16 authoritative control outstanding, AED 63,342.75 invoice evidence, 32 parties requiring reconciliation review.
- Payable report: 59 parties, AED 31,665.00 authoritative control outstanding, AED 31,672.72 positive invoice evidence, 11 parties requiring reconciliation review.
- Preserved trial-balance evidence: AED 930,029.02 debit, AED 862,301.36 credit, AED 67,727.66 difference.

These differences are displayed as source-quality exceptions and are not corrected automatically.

## Verification and safety state

- Full automated suite: 119 passed; one optional PostgreSQL integration test skipped because its dedicated disposable test URL is not configured.
- JavaScript syntax and Python compilation checks passed.
- Docker frontend and backend are healthy on `127.0.0.1:18082`.
- Operational schema remains `0013`; no schema expansion was required for read-only reporting.
- Permanent posting remains disabled.
- No payment, allocation, journal or subledger rows were created during deployment.
- BizModo was not accessed or modified by the report build.
- HRM and payroll remain excluded.

## Next enterprise increment

Complete posting and reversal integration across operational sales, purchases, inventory, goods receipts, returns and payments. Activation must remain disabled until journal, stock and subledger effects reconcile atomically and rollback/reversal tests pass.
