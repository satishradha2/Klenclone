# Finance reconciliation workflow checkpoint

Date: 2026-09-15

## Outcome

The independent Asas ERP now has a database-backed maker/approver workflow for
the current test-data finance reconciliation controls. It covers the preserved
trial-balance difference and the opening AR/AP header/report variances.

Each review is bound to its source snapshot or opening-balance manifest and
stores the authoritative amount, comparison amount, variance, proposed
disposition, maker, approver, notes and revision.

## Allowed dispositions

- Recheck during the final fresh BizModo sync.
- BizModo source correction required.
- ERP import-mapping correction required.
- Accept for test-data evaluation only.

Approval records that a proposed plan received independent review. It does not
balance the ledger, clear the underlying financial exception, amend BizModo,
enable posting or carry approval into the final fresh import.

## Controls

- Separate `finance.reconciliation.prepare` and
  `finance.reconciliation.approve` permissions.
- Makers cannot decide their own plans.
- Decisions require the current revision.
- Every request and decision is audited.
- Posting remains disabled at both model and application levels.
- The current data and decisions are explicitly marked test-only and must be
  deleted before the final complete BizModo import.

## Verification

- JavaScript syntax check: passed.
- Dedicated reconciliation state-machine test: passed.
- Full automated suite: 158 passed, 1 skipped.

