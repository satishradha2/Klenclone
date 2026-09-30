# Cross-border delivery readiness checkpoint (2026-09-28)

The accepted foreign quotation and independently released sales order remain the commercial source of truth. This increment introduces a separate, order-bound delivery readiness record in the existing Deliveries workspace.

## Released in controlled staging

- A logistics/warehouse maker records the transport plan, expected customs/shipment evidence, evidence reference and validity date against a confirmed foreign order.
- A different authorized reviewer approves or rejects it. The reviewer cannot be the readiness maker, order maker or quotation maker. Decisions and preparation are audited, revision-checked and tied to the order snapshot.
- A current approved readiness allows stock allocation and picking, with the existing availability, UOM, reservation and lot checks still in force.
- Expired readiness or a changed order blocks allocation/picking; a new readiness may be prepared after expiry.

## Still held

- Foreign dispatch and stock issue are not authorized by readiness alone; they now require a separate reviewed dispatch release. Invoice creation, tax determination and accounting posting remain held after POD.
- A transport plan or evidence reference is not proof of export or a zero-rate VAT decision. The dispatch release reviews shipment references; document-level export proof and invoice-tax treatment still require separate control.
- The BizModo source remains read-only. These records live only in the clone's operational database.

## Verification

Focused tests cover missing readiness, independent review, successful allocation/pick and blocked dispatch without the separate release. The earlier full local suite passed: 290 passed, 1 skipped. The rebuilt preview returned healthy with its operational database reachable. The authenticated Deliveries tabs were visually checked; named business-user UAT remains a separate release gate. The subsequent dispatch increment has its own checkpoint.
