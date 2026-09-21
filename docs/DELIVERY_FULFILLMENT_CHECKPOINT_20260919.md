# Delivery fulfilment checkpoint — 2026-09-19

## Delivered

- Confirmed sales orders can be allocated only against approved available stock at the order location.
- Delivery reservations use a dedicated immutable link to the sales order and preserve SKU, entered quantity, UOM, canonical UOM and factor-to-base snapshots.
- Picking confirms the complete allocated quantity without changing physical on-hand stock.
- Dispatch creates a unique delivery note, consumes the exact active reservation, reduces operational on-hand stock and records a delivery-specific stock movement.
- Proof of delivery requires receiver name, POD reference and evidence note. Only the delivered state is invoice-eligible.
- Cancellation before dispatch releases the reservation. Cancellation after dispatch is prohibited.
- Every transition uses optimistic revision checks and immutable workflow/audit events.

## Safety boundary

The workflow changes only the target ERP test-data database. It does not write to BizModo. Delivery stock issues do not create accounting journals or subledger entries, and global accounting posting remains disabled. All test operational data is deleted before the final fresh BizModo import.

## Verification

- Operational schema migration registry: `0033`.
- Automated suite: 183 passed, 1 skipped.
- Tested controls cover unavailable stock, UOM and availability gates, idempotent allocation, exact reservation release/consumption, dispatch stock issue, POD invoice eligibility, cancellation boundaries, revisions and zero accounting journals.
- Live browser workflow: sales order `SO-20260919-E61D02C9` produced fulfilment `DF-C69CBD59`, delivery note `DN-C69CBD59` and POD `POD-BROWSER-20260919-001`.
- Live quantity evidence is exactly 1.000000 at ordered, allocated, picked, dispatched and delivered stages. The delivery reached revision 4 and became invoice-eligible; journal and subledger counts remained zero.

## Next checkpoint

Customer invoicing should select only delivered, POD-backed sales orders, preserve the delivery/order chain and prevent duplicate or excess invoicing. Accounting and inventory-cost posting must remain behind the existing global activation gate.
