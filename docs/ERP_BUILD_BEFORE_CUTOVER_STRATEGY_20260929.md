# ERP build-before-cutover strategy — 2026-09-29

## User-confirmed operating plan

The present BizModo exports and cloned records are **development and test evidence only**. They contain known source errors, including duplicate document numbers, inconsistent tax/report rounding, conflicting stock values, unbalanced accounting reports and snapshot drift. Their calculated totals are not authoritative ERP results. Do not change correct target-ERP calculations merely to reproduce a BizModo number.

Complete and validate the new ERP **before** final migration. At cutover, stop new BizModo transactions under a controlled business freeze, take a complete final **read-only** capture, reconcile and import that capture with documented exception treatments, and then create all new transactions in the new ERP. Never write back to BizModo. Existing cloned records and test transactions must not be mistaken for the final operational opening state.

## Next build increment: domestic calculation and posting correctness

Create an executable acceptance matrix across the existing operational modules, using target-side synthetic transactions plus selected preserved BizModo anomalies as negative/regression fixtures. Explicitly define and test:

1. Decimal precision and rounding per AED line, document, discount allocation and VAT amount; ensure line sums equal document and journal totals.
2. Product-specific UOM snapshots, fractional packs/cartons, barcode identity and stock quantity/value changes; never use a global carton factor.
3. Purchase order -> receipt -> supplier invoice -> payment, including partials, returns, credit/debit notes, tax evidence and exact reversals.
4. Quotation -> sales order -> allocation/delivery -> invoice -> receipt/return, including customer credit, discounts, tax, COGS and exact reversals.
5. Cross-ledger invariants: balanced journals, inventory valuation, customer AR, supplier AP, cash/bank, VAT control and period close; failed or duplicate commands must be atomic and idempotent.
6. Role/location/maker-checker restrictions and browser-level job completion, not only isolated unit calculations.

The first vertical slice should be one domestic AED product with two UOMs through purchase receipt, stock, sale, return and payment, including fractional quantities and an invoice-level discount. Add a golden expected-results table **derived from approved ERP rules**, not from BizModo report totals. Extend the same matrix to zero/negative stock, duplicate legacy references, partial deliveries, credits, retries and reversal-after-later-activity boundaries. Fix each discovered target-code defect before expanding coverage.

## Later release sequence

After core correctness and remaining functional modules pass integrated UAT, perform a full disposable import rehearsal. Only then arrange the final BizModo freeze/capture, reconcile source identities and opening positions, remove test data, import the final dataset, run named acceptance and cut over. The 13 remaining historical review exceptions are inputs to migration policy and tests; they are **not** a reason to migrate today's test snapshot or activate production early. Posting remains disabled until the separately approved final release.
