# Sales quotation and order checkpoint — 2026-09-19

## Delivered

- Customer quotations use active customer, location, product and approved base-UOM masters.
- Quotation lines preserve entered quantity, UOM, canonical UOM and the factor-to-base snapshot.
- Draft and rejected quotations may be revised using optimistic revision checks.
- Submit, cancel, approve and reject actions are audited; approval/rejection requires an independent user and a reason.
- Customer acceptance requires an approved, unexpired quotation and an acceptance reference.
- An accepted quotation converts idempotently to one confirmed sales order. Header totals and line snapshots are copied exactly.
- The visible Sales orders workspace supports creation, revision and every workflow transition permitted to the signed-in role.

## Safety boundary

This checkpoint does not reserve stock, create a delivery note, generate an invoice, post a journal or write to BizModo. `posting_enabled` and `stock_reservation_enabled` remain false. All current operational records are test data and are to be deleted before the final fresh full BizModo import.

## Verification

- Operational schema migration registry: `0032`.
- Automated suite: 180 passed, 1 skipped.
- Covered controls include duplicate product rejection, date validity, maker-checker segregation, expiry, revision conflict behavior, immutable/idempotent conversion, and zero stock-reservation/accounting side effects.
- Live browser workflow: `SQ-20260919-A0972CAA` was independently approved, accepted with customer evidence and converted to confirmed order `SO-20260919-E61D02C9` for AED 10.50.
- The live reservation count remained unchanged during conversion; journal and subledger entry counts remained zero.
- Future order conversions use an auditable reason dialog instead of a native browser confirmation.

## Next checkpoint

Delivery fulfilment should add allocation/reservation, pick, dispatch and proof-of-delivery controls against the confirmed sales order. Those controls must remain distinct from invoice and permanent posting activation.
