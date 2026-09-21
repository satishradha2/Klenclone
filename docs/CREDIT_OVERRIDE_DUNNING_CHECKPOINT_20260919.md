# Credit override and dunning checkpoint — 19 September 2026

## Outcome

The target Asas ERP now controls two exceptions that were still open after the customer-credit foundation:

- a sales order blocked by a customer hold or insufficient available credit can proceed only through an independently approved, quotation-specific, one-time override; and
- collection escalation follows a controlled reminder sequence with independent approval and an auditable completion decision.

BizModo remains read-only. These controls affect target-ERP test workflows only, and permanent stock and accounting posting remain disabled.

## Blocked-order override

1. The system identifies an accepted quotation whose conversion is blocked by an active hold or projected exposure above the approved limit.
2. An authorised maker requests an override for that exact quotation and order amount, provides a business justification, and selects a validity date no more than 30 days ahead.
3. A different authorised checker approves or rejects the request. Self-approval is blocked.
4. Order conversion accepts only an approved, unexpired request matching the customer, quotation, and amount snapshots.
5. Successful conversion consumes the override and records the resulting sales-order key. The approval cannot be reused for another order.

An override does not remove the customer's hold or revise the credit limit. It authorises only the documented exception.

## Collection escalation

Escalation stages are `reminder_1`, `reminder_2`, `final_notice`, and `legal_referral`. A customer becomes eligible when there is a reliable overdue target-ERP invoice or a broken promise to pay. Each request snapshots exposure, overdue value, broken promises, reason, and planned action.

Stages must be requested sequentially. Each stage requires an independent approval before it can be completed. Rejected or cancelled requests remain in the audit history and do not advance the sequence.

Migrated opening balances still count toward exposure but do not become overdue merely because the source due date is unreliable.

## Permissions

- `credit.override.prepare` creates a blocked-order override request.
- `credit.override.approve` approves or rejects it independently.
- `collection.escalation.prepare` creates a dunning-stage request.
- `collection.escalation.approve` approves, rejects, or completes it independently.

All mutations require authenticated permission and CSRF protection.

## User interface

The Credit control workspace now includes:

- blocked-order, pending-override, and pending-dunning metrics;
- a blocked-quotation override request form;
- a one-time override approval queue with consumed and expired states;
- a collection-escalation request form limited to eligible customers; and
- a dunning queue showing its evidence snapshot, approval state, and completion action.

When there are no eligible records, the page displays explicit empty-state guidance instead of offering an invalid action.

## Verification

- Full regression: **196 passed, 1 skipped**.
- JavaScript syntax checks and Python compilation passed.
- Docker preview rebuilt successfully and health reports `ok` on `http://127.0.0.1:18082/`.
- Operational schema migration count is **37**, including migration marker `0037`.
- Permanent posting remains disabled.
- The existing test customer retained its approved AED 500 limit, AED 84 exposure, AED 416 available credit, and open promise-to-pay record.
- Current data correctly produces no blocked-quotation override candidate and no dunning candidate: there is no accepted quotation over the available limit, no reliable overdue target-ERP invoice, and the promise is not broken.

The records remain test data and will be removed as part of the complete target-ERP test-data purge before the final full BizModo import.
