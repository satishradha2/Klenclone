# Domestic target-invoice return checkpoint — 29 September 2026

Build-stage synthetic test result, not production acceptance. BizModo source data remains read-only.

## Implemented in staging

- The Sales Returns invoice selector now includes approved target-ERP invoices as well as preserved BizModo invoice evidence, with source labels.
- A target return records explicit invoice origin and target invoice key. Revision `0063` adds these provenance columns to the operational schema through the explicit migration path.
- The return uses the approved invoice's SKU, entered UOM, original price, VAT rate, discount and total as its evidence. Duplicate SKU lines, changed invoice evidence, stale partial-return pricing, excess quantity and credits beyond the unpaid balance are rejected. Pricing-only corrections are held for a separate adjustment workflow.
- Each partial credit allocates the original line's **discounted** net and VAT cumulatively at AED cent precision. The final return takes the rounding remainder, so two one-unit returns against the synthetic AED 19.95 invoice credit AED 9.98 and AED 9.97, exactly AED 19.95 in total.
- Approved target credits reduce customer open items, payment capacity, statements, credit exposure and AR ageing. A posted AED 6.00 receipt plus AED 9.98 credit leaves AED 3.97 outstanding. A further credit requiring a refund is held rather than making the receivable negative.

## Deliberate posting hold

Approval creates a controlled, **non-posting** credit note. Target-invoice return posting is blocked because the current target delivery/invoice path has not posted the original accounting and immutable issue-cost valuation. Approval does not restock inventory or post a VAT/AR journal. This prevents a return from reversing a cost entry that does not exist. The next increment must establish original invoice/dispatch posting and cost snapshots, then link return restock, VAT and AR posting to that source; separately implement a governed customer-refund workflow for returns exceeding unpaid receivables.

The existing BizModo-backed return path is unchanged. Historical as-of reports after later reversal still need event-time reconstruction; current report filters operate on current status and document dates.
