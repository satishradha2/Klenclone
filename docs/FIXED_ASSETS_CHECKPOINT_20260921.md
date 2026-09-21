# Fixed-assets checkpoint — 2026-09-21

## Implemented scope

- Target-ERP fixed-asset register with category, acquisition evidence, location,
  cost centre, custodian, serial number, cost, residual value and useful life.
- Maker-checker capitalization approval with revision checks and mandatory
  decision notes. The asset creator cannot approve the same asset.
- Straight-line monthly depreciation schedules generated only after approval.
- Controlled disposal request and independent approval. The disposal requester
  cannot approve the same disposal.
- Fingerprinted, idempotent capitalization, depreciation and disposal journal
  rehearsals. Every rehearsal must balance and remains non-posting.
- Location-scoped APIs, permission-controlled navigation and visible workflow
  actions for the independently provisioned ERP users.

## Accounting rehearsal rules

- Capitalization: debit the snapshotted asset account and credit Asset
  Acquisition Clearing.
- Depreciation: debit the snapshotted depreciation-expense account and credit
  accumulated depreciation for the selected schedule month.
- Disposal: clear cost and accumulated depreciation, recognize proceeds, and
  calculate the balancing gain or loss.

These are planning journals only. `posting_enabled` and `posting_performed`
remain false, and the BizModo source is never written.

## Validation

- Unit coverage validates full schedule value, residual value, maker-checker
  rejection, balanced journals, idempotency and disposal control.
- API coverage uses the deployed `operations_administrator` and
  `independent_approver` role names and confirms permanent posting stays off.
- Browser UAT is required after deployment for draft, approval, first-month
  depreciation, disposal and final rehearsal visibility.
