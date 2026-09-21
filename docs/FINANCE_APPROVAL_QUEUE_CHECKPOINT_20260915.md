# Finance Approval Queue Checkpoint — 2026-09-15

## Delivered scope

The Full-IFRS chart accounts and workflow mappings now use a database-backed maker/approver state machine in the independent Asas ERP operational database.

- Finance Makers can submit individual chart accounts and account mappings for review.
- Finance Approvers can approve or reject pending items.
- The requester cannot approve or reject their own request.
- Every decision requires an explanatory note.
- Optimistic revisions prevent stale or duplicate decisions.
- Database row locks serialize concurrent request and decision processing.
- Approved chart accounts become active.
- Approved workflow mappings become eligible for the later draft-journal workflow.
- Rejected resources remain inactive and can be revised and resubmitted.
- Requests and decisions create immutable operational audit events.

## API and interface

The **Chart of accounts** workspace includes the live Finance Approval Queue and permission-aware actions.

- `POST /api/v1/finance/approvals/{resource_type}/{resource_key}/request`
- `POST /api/v1/finance/approvals/{resource_type}/{resource_key}/approve`
- `POST /api/v1/finance/approvals/{resource_type}/{resource_key}/reject`

Chart requests require `finance.chart.prepare`; chart decisions require `finance.chart.approve`. Mapping requests require `finance.mapping.prepare`; mapping decisions require `finance.mapping.approve`. Every mutation also requires authentication and CSRF validation.

## Safety state

Approval changes only target the separate Asas ERP operational configuration. BizModo records, identities and evidence remain read-only. Approval does not create a journal or enable posting. The global posting and production gates remain disabled.
