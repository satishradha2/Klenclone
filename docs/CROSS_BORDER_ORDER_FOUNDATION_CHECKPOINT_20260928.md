# Cross-border order foundation checkpoint

Date: 2026-09-28

The first downstream increment is discount and taxable-line reconciliation for
customer quotations. A header discount is apportioned across quotation lines
in two-decimal minor units, with deterministic remainder allocation. Line tax
is recalculated on the discounted line amount, and line gross totals must sum
to the document total. This applies to both UAE and currently enabled
two-decimal cross-border quotation currencies. The approved commercial
discount ceiling, currency-specific price list, provisional trade decision,
and exact-date FX reference remain required for foreign quotations.

Quotation, sales-order, and customer-invoice lines now retain the allocated
discount snapshot. Additive operational schema migration 0057 adds the field
to existing line tables with a zero default; existing amounts are not rewritten.
Legacy accepted quotations or orders whose lines do not reconcile to their
header are held from conversion or invoicing for explicit review.

## Still held

- Cross-border quote-to-order conversion is **not** released. A provisional
  quotation trade decision is not order authority or final invoice tax evidence.
- BHD, KWD, and OMR three-decimal money precision is not yet supported by the
  quotation schema or input contract.
- Foreign-currency credit exposure, order-stage trade/tax approval, delivery
  evidence, invoice tax/FX treatment, and settlement controls are not complete.
- Posting and production activation remain disabled. BizModo source data is
  never written.

## Verification

Focused quotation, delivery-to-invoice, and cross-border service tests cover
mixed-tax line allocation, FX snapshot recalculation, approval discount ceiling,
snapshot propagation, and legacy-document rejection. The authenticated HTTP
cross-border quotation test also verifies the allocated discount in the API.
The full local suite passed with 284 tests, 1 existing optional skip, and 2
dependency deprecation warnings. The preview was rebuilt and reported healthy:
both databases reachable, authentication enabled, and posting disabled.
Named business-user acceptance and an authenticated browser walkthrough remain
separate release gates.
