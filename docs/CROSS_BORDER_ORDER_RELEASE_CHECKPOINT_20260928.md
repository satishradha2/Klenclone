# Cross-border order recording checkpoint — 28 September 2026

## Implemented

- An accepted non-UAE quotation can be submitted for a distinct order-stage tax/trade release. The request records the reviewer basis, required pre-fulfillment evidence, source reference and expiry, bound to a fingerprint of the quotation revision and monetary/FX/line snapshots.
- A different reviewer must approve or reject. Neither the release maker nor the quotation maker may approve. Changed or expired quotations invalidate the release.
- Conversion requires a current approved release and a configured active AED customer credit profile with sufficient available limit. Foreign amounts are never added to AED exposure as if they were AED; the quotation's approved FX-derived AED snapshot is used. The existing AED-only credit override path cannot be used for foreign quotations.
- Cross-border orders retain currency precision (including three-decimal GCC currencies), FX/AED snapshots and the consumed release reference. They remain non-posting.
- Stock allocation, delivery and customer invoicing remain explicitly blocked. Invoice tax, customs/export evidence, settlement and posting are **not** released by this increment.
- The Sales Orders workspace contains the release request/review beside the quotation register. Foreign orders display their currency, AED credit reference and delivery/invoice hold.

## Validation and release boundary

- Domain and route tests cover maker-checker, stale snapshots, absent/over-limit credit, BHD/KWD/OMR precision, AED exposure, idempotent conversion and delivery/invoice holds.
- This is staging implementation, not a business or tax ruling. Named tax/finance business-user acceptance and documentary policy sign-off are still required before enabling any downstream cross-border delivery or invoicing.
- BizModo source data remains read-only. No production posting is enabled.
