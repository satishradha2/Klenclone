# Delivery-backed customer-invoice posting checkpoint (29 September 2026)

## Implemented

- A domestic, maker-checker-approved target-ERP customer invoice can enter the existing governed integrated-posting route as `customer_invoice`. It must have a balanced five-account rehearsal tied to matching dispatch-cost snapshots and an open fiscal period. Idempotency is bound to invoice revision and rehearsal fingerprint.
- Atomic posting records AR, revenue, output VAT, COGS and inventory journal lines plus a customer receivable subledger entry. It creates **no** second stock movement: dispatch already reduced physical stock.
- Posted invoices remain eligible for receipt allocation, settlement, ageing, statements, VAT-source review, credit exposure and target-return creation. A reversal restores accounting and subledger entries only; it is refused if an active receipt allocation or non-cancelled dependent return exists. Reversed invoices cannot receive new allocations.
- The invoice control board shows posting/reversal actions only when global posting activation and the appropriate permission are both present. The current staging configuration remains non-posting; no production activation is performed here.

## Still gated

- Original target invoice posting and its target-return stock/AR/VAT follow-on are now available in code; see `DOMESTIC_TARGET_RETURN_POSTING_CHECKPOINT_20260929.md`. Customer refunds and pricing-only credits remain separate held workflows.
- Historical AR-only rehearsal rows cannot be silently reused as costed plans; they require reviewed remediation. Unvalued or zero-cost dispatches are also held.
- PostgreSQL `0065` migration rehearsal and named operational acceptance remain release gates. A passing SQLite suite alone does not authorize a production switch or alteration of BizModo data.
