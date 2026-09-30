# Domestic calculation correctness checkpoint — 29 September 2026

This is a build-stage test checkpoint, not cutover or release approval. BizModo source data remains read-only; final extraction, transaction freeze, import and reconciliation are later gates.

## Confirmed defect and correction

The legacy draft path previously subtracted a header discount from the document total but retained VAT calculated on the undiscounted lines. Draft creation and revision now allocate the header discount over line net amounts (deterministic largest remainder at AED 0.01) and calculate VAT on each discounted taxable amount. Entered quantity, UOM factor, base quantity, net, VAT, gross and cost are checked or recalculated from the entered facts instead of trusting caller-supplied totals.

## Synthetic domestic control case

One half carton × six packs per carton = three packs. At AED 24 per carton and AED 1.20 document discount: subtotal AED 12.00, taxable sales AED 10.80, 5% VAT AED 0.54, receivable AED 11.34. At AED 2.35 per pack: inventory/COGS AED 7.05. The test checks persisted draft values, approval/stock reservation, balanced posting, stock decrement, receivable and VAT journal lines, and idempotent replay.

The quantities and prices above are synthetic test inputs, not approved BizModo facts or a production opening balance.

## Still open

This checkpoint does not certify the whole ERP, all domestic document types, reports, tax policy, migration or live posting. The next correctness slices should extend the same trace to payment allocation and returns, then compare transaction ledgers with financial reports and period-close controls. Before cutover, run a frozen-source extraction, independently reconcile opening balances and historical documents, obtain named business/finance acceptance, and authorize go-live separately.
