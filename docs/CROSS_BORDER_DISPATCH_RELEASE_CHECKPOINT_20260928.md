# Cross-border physical dispatch checkpoint (2026-09-28)

This increment extends the foreign order and delivery-readiness controls in the existing Deliveries workspace. It is a controlled staging flow, not a production export, tax, or accounting release.

## Release path

1. A foreign order must have an independently approved order release and delivery-readiness record before reservation and picking.
2. Once picked, a logistics maker records carrier, transport/booking, packing-list, customs declaration/clearance, destination consignment references, and a validity date against the immutable fulfillment and active lot allocation snapshot.
3. A different authorized reviewer approves or rejects the physical dispatch release. The reviewer cannot be its maker, the fulfillment maker, the order maker, or the quotation maker. Expiry or snapshot drift prevents release.
4. Dispatch revalidates current readiness, lots, quantity, and stock; it consumes the dispatch approval in the same transaction as the operational stock issue. The existing delivery note and proof-of-delivery workflow then applies.

The references are identifiers for independently reviewed records, not uploaded document verification or proof that goods left the UAE. A later tax control must evaluate actual export evidence and determine invoice treatment. The Federal Tax Authority's [VATP040 clarification](https://tax.gov.ae/Datafolder/Files/Pdf/2025/VATP040%20-%20Amendments%20to%20VAT%20ER%20-%2014%2003%202025.pdf) describes evidence combinations for zero-rating exports; this dispatch workflow does not infer zero-rating from destination or these references.

## Holds retained

- Foreign customer invoices remain blocked after POD, and the Deliveries UI does not count them as invoice-eligible.
- Accounting posting and production activation remain disabled.
- BizModo source data remains read-only; all new records are in the clone's operational database.

## Verification

Unit and API tests exercise missing approval, self-review denial, independent review, physical dispatch, POD, and continuing invoice hold. The full local suite passed (290 passed, 1 skipped), and the rebuilt preview reports healthy with its operational database reachable. In the signed-in browser, the cross-border readiness and dispatch registers, their hold messaging, and the domestic delivery control board rendered correctly. No foreign staging shipment records existed to exercise the new action buttons against live preview data; named business-user acceptance and document-level evidence verification remain release gates.
