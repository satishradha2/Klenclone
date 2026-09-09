# Inventory operations foundation checkpoint

Date: 2026-09-09

## Outcome

The independent Asas ERP now has a controlled operational foundation for stock
transfers and stock adjustments. It uses the existing clone product/location
masters and the isolated operational database. BizModo was not modified.

Permanent inventory posting is still disabled. This checkpoint supplies draft,
submission, approval and posting-rehearsal behavior so the workflow can be
verified before production activation or the later full BizModo refresh.

## Document controls

- Supported document types: inter-location transfer and stock adjustment.
- Transfers require different source and destination locations.
- Adjustments require an explicit increase or decrease direction and reason.
- Every line preserves entered UOM, canonical UOM,
  `factor_to_base_snapshot`, `quantity_base`, unit-cost snapshot and value.
- Outgoing transfers and decreases reserve approved available stock under row
  locks when submitted.
- Insufficient stock, unavailable stock, location-scope violations and UOM
  mismatches fail closed.
- Cancelling a submitted document releases its reservations.
- A document creator cannot approve the same document.
- Optimistic revisions prevent stale workflow changes.
- Draft-state documents can be edited. Every edit revalidates locations,
  products, UOMs and cost evidence, replaces the line set transactionally and
  increments the revision. Submitted or stale documents cannot be edited.
- Workflow and operational audit events are append-only.

## Posting rehearsal

- Rehearsal requires an approved document and an open rehearsal-enabled fiscal
  period.
- A transfer produces equal and opposite source/destination quantity and value
  legs, with zero company-wide quantity and value change.
- An adjustment produces a balanced Inventory / Inventory Adjustment journal.
- The plan includes a deterministic SHA-256 fingerprint and idempotency key.
- Rehearsal creates no permanent journal, inventory movement or BizModo row.

## Authenticated API

- `GET /api/v1/inventory-documents`
- `GET /api/v1/inventory-documents/{document_key}`
- `POST /api/v1/inventory-documents`
- `PUT /api/v1/inventory-documents/{document_key}?expected_revision=...`
- `POST /api/v1/inventory-documents/{document_key}/submit`
- `POST /api/v1/inventory-documents/{document_key}/cancel`
- `POST /api/v1/inventory-documents/{document_key}/approve`
- `POST /api/v1/inventory-documents/{document_key}/posting-rehearsal`

The maker has `inventory.create`, `inventory.edit`, `inventory.submit` and
`inventory.cancel`.
The independent approver has `inventory.approve` and `inventory.rehearse`.
Both remain limited to their assigned location scopes.

## Schema and verification

- Operational schema revision: `0008`
- New document, line, reservation, workflow, posting-batch and posting-entry
  tables are versioned in the operational schema.
- Focused inventory/API tests: 11 passed.
- Full automated suite: 94 passed, 1 expected isolated-PostgreSQL skip.
- The established `klen-copy-validation` Docker preview was rebuilt without
  replacing either PostgreSQL volume. Health, authentication and both database
  connections passed after restart.
- Live database preservation check: eight migration rows, 579 stock positions,
  264 staged opening party balances and zero inventory documents.
- Browser verification passed for the new `Stock operations` navigation item,
  transfer/adjustment form, control metrics and empty workflow queue.
- The deployed page includes draft editing controls and the deployed OpenAPI
  contract exposes the authenticated `PUT` operation.
- Production posting remains disabled.

## Next enterprise increment

Add inventory-document editing and review UI, then implement controlled goods
receipt, sales return/credit note and purchase return/debit-note workflows on
the same posting, reservation, approval and audit primitives.
