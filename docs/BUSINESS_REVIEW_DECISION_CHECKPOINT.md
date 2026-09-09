# Business review decision checkpoint

Date: 2026-09-09

## Outcome

A permission-protected, checksum-bound business-review decision workflow is active in the isolated UAT service. Decisions are append-only sidecar metadata and cannot alter BizModo, the cloned business database, package contents, migration exceptions, approval policies, or posting state.

## Initial synthetic decisions

| Module | UAT decision | Reason |
|---|---|---|
| Customers | Conditionally accepted for UAT | Technical package prepared; business-owner confirmation remains required |
| Suppliers | Conditionally accepted for UAT | Technical package prepared; business-owner confirmation remains required |
| Products | Conditionally accepted for UAT | Product and UOM package prepared; business-owner validation remains required |
| Sales | Evidence requested | 120 package discrepancy rows and control-total differences require review |
| Purchases | Evidence requested | 109 package discrepancy rows and control-total differences require review |
| Inventory | Evidence requested | 40 discrepancy rows and 12 incomplete quantity-formula evidence rows require review |
| Accounting | Evidence requested | 126 discrepancy rows require review despite zero blueprint debit-credit variance |

All seven decisions are version 1, recorded by `synthetic.uat.reader`, scoped to `MAIN`, and bound to the SHA-256 values in the corrected package index.

## Controls

- A package must be downloaded before the browser enables its decision button, binding the form to the returned package checksum.
- Each module decision endpoint rechecks that module's permission.
- POST requests require the active UAT session and CSRF token.
- Allowed states are `accepted_for_uat`, `conditionally_accepted_for_uat`, `rejected_for_uat`, and `evidence_requested`.
- Database triggers reject updates and deletes of decisions and review events.
- Later judgments create a new version; history is not overwritten.
- Every decision is forced to `synthetic_only = true` and `production_signoff = false`.
- There is no production-signoff, approval, activation, posting, or source-mutation endpoint.

## Verification

- Application suite: 58 passed, 1 PostgreSQL-only test skipped outside its isolated profile.
- Authenticated technical UAT: 82 passed, 0 failed.
- Browser verification rendered all seven decisions with `Production sign-off = false`.
- Browser verification also downloaded a fresh package, enabled its checksum-bound decision button, and displayed the synthetic-only decision form without submitting another decision.

## Remaining business work

The four evidence-requested modules remain blocked for business acceptance. The three conditionally accepted master-data modules remain blocked for production acceptance until accountable business owners compare them with independent source reports.
