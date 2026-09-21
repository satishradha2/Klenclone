# Customer credit and collections checkpoint — 19 September 2026

## Outcome

The target Asas ERP now has a controlled customer-credit workspace covering approved credit limits, payment terms, receivable and sales-order exposure, customer holds, overdue monitoring, collection follow-ups, and promise-to-pay tracking. BizModo remains read-only and permanent accounting posting remains disabled.

This checkpoint does not treat the test import as final production data. Its records are target-ERP test records and may be deleted with the rest of the test dataset before the final full BizModo import.

## Control flow

1. An authorised credit maker proposes a customer limit and payment terms with a reason.
2. A different authorised approver approves or rejects the request. Self-approval is blocked.
3. Approval creates or revises the active credit profile; the approval queue and audit events retain the decision evidence.
4. Credit exposure combines approved opening receivables, approved target-ERP invoices, approved receipts, customer advances, and uninvoiced confirmed sales orders.
5. Quotation-to-order conversion is blocked when an approved profile is on hold or when the new order would exceed available credit. Customers without a configured profile remain allowed during controlled staging so legacy test workflows are not silently broken.
6. An authorised controller can place or release a customer hold with a mandatory reason.
7. Collection users can record calls, emails, visits, final notices, legal referrals, and promises to pay. Promise amount and date are mandatory for a promise-to-pay action; open actions can be completed, marked broken, or cancelled.

## Overdue scope

Only approved target-ERP invoices with reliable due dates are classified as overdue. Migrated opening balances continue to count toward credit exposure, but they are not assigned an invented due date or falsely reported as overdue. This distinction is displayed in the workspace.

## User interface

The Finance navigation now includes **Credit control**. Customer selectors and tables display the customer name only; the customer code remains an internal record key. The workspace provides:

- configured, over-limit, on-hold, and overdue control totals;
- credit-limit request and independent approval queues;
- customer exposure, open-order commitment, available credit, overdue balance, and next follow-up;
- customer hold and release controls; and
- collection and promise-to-pay history.

## Security and posting posture

- `credit.limit.prepare` creates requests.
- `credit.limit.approve` approves or rejects them independently.
- `credit.hold.release` controls holds and releases.
- `collection.manage` records and updates follow-up actions.
- All mutations require authenticated permission and CSRF protection.
- Credit controls affect target-ERP order conversion only.
- No credit or collection action changes BizModo.
- No action creates a permanent journal or enables posting.

## Verification

- Focused credit-management, route-wiring, sales-order, and customer-invoice tests passed.
- Full regression: **193 passed, 1 skipped**.
- JavaScript syntax checks passed for the credit workspace and ERP router.
- Docker preview rebuilt successfully and is healthy on `http://127.0.0.1:18082/`.
- Operational schema migration count is **36**, including migration marker `0036`.
- Health reports permanent posting disabled.

## Live browser UAT

The deployed workflow was exercised using independent roles:

- `asas-admin` requested an AED 500 limit with 30-day terms for Al mas pack plastic trading.
- `asas-approver` independently approved the request after reviewing the current AED 84 exposure.
- The approved profile displayed AED 416 available credit and `within_limit` status.
- The approver placed a test hold, the workspace reported one on-hold customer, and the hold was then released with a separate audit reason. The customer was left active.
- `asas-admin` recorded a test-only AED 84 promise to pay for 22 September 2026 against the opening exposure. It appears as one open promise and the next follow-up date.
- The opening exposure remains outside the overdue total because its migrated due date is not reliable; target-ERP overdue invoices remain zero.
- The first live mutation attempt exposed a missing central middleware allowlist entry for `/api/v1/credit-control`. The route was added to the controlled operational-mutation set, a regression test was added, the preview was rebuilt, and the complete live workflow then passed.

The live records remain test data and will be removed with the full target-ERP test-data purge before the final BizModo import.
