# POS and counter-sales checkpoint — 21 September 2026

## Implemented

- Controlled till master by operating location.
- One open shift per till with opening float and immutable shift numbering.
- Counter receipts using active product price, UOM and UAE VAT snapshots.
- Cash and card controls, including cash change and exact card settlement.
- Stock-availability validation when operational availability is enabled.
- Cash-close submission with expected cash, counted cash and variance.
- Independent close approval with maker-checker enforcement.
- Append-only audit events for till creation, shift opening, sale, close submission and approval.

## Safety boundary

This is controlled staging and test data only. POS sales do not update permanent stock, create accounting journals, post VAT, or activate production. BizModo remains read-only. All target test rows will be deleted before the final fresh import.

## Verification

- Migration registry: `0047`
- POS operational tables: 5
- Full automated suite: 232 passed, 1 skipped
- Live preview health: healthy on `127.0.0.1:18082`
- Integrated posting batches after deployment: 0

## UAT sequence

1. Administrator creates a till and opens a shift.
2. Cashier records a test counter sale and submits the counted cash.
3. Independent approver reviews the variance and approves the close.
4. Confirm the receipt, audit events and zero-posting boundary.

## Live UAT result

- Till: `UAT-TILL-1` at `MAIN`
- Shift: `POS-SH-20260921-0EF517`
- Receipt: `POS-20260921-DF21CE88`
- Sale: AED 1.40 including AED 0.07 VAT; AED 10.00 tendered and AED 8.60 change
- Close: AED 101.40 expected and counted; AED 0.00 variance
- Maker self-approval: blocked
- Independent close: approved as `asas-approver`
- POS audit events: 5
- Integrated posting batches: 0
