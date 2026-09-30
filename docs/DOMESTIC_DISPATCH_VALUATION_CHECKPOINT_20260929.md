# Domestic dispatch valuation checkpoint (29 September 2026)

This increment is a controlled accounting foundation, not a production posting release. BizModo remains read-only. The target ERP already deducts physical stock at delivery dispatch; the customer invoice must not deduct it again.

## Implemented

- Each new dispatch stock movement captures the locked pre-issue average unit cost and monetary issue value, alongside SKU, location, base quantity, delivery line and timestamp. Later receipts or cost changes do not reprice that issue.
- Approved target-ERP customer-invoice rehearsal requires an exactly matching valued dispatch movement for every invoiced line. Its balanced journal now includes AR, revenue, output VAT, COGS and inventory. There is no second inventory movement.
- Existing historical dispatch rows are left with null valuation. Rehearsal fails closed for those rows, and for zero-cost issues, pending genuine evidence review; today's average cost is not substituted.
- The dispatch-valuation schema step was `0064`; the subsequent delivery-backed customer-invoice posting step advances the current contract to `0065`. Production startup still performs read-only preflight; the operator-run migration remains a separate step.

## Still gated

- Customer-invoice integrated posting was added in the following increment; see `DOMESTIC_CUSTOMER_INVOICE_POSTING_CHECKPOINT_20260929.md`. Target-ERP sales returns and refunds remain held.
- The current `0065` PostgreSQL migration must be rehearsed against a fresh isolated database and backed-up staging database before deployment. The automated PostgreSQL migration test skips without its dedicated test URL.
- Existing unvalued dispatches require provenance-based cost reconciliation before any accounting activation.
