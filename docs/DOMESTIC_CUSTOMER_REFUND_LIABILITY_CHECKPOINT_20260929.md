# Customer-refund liability checkpoint (29 September 2026)

> Historical checkpoint. The later payout increment is recorded in [DOMESTIC_CUSTOMER_REFUND_PAYOUT_CHECKPOINT_20260929.md](DOMESTIC_CUSTOMER_REFUND_PAYOUT_CHECKPOINT_20260929.md); the open items below describe this earlier liability-only state.

## Implemented in the target ERP

- A returned item can be credited after a customer has already paid part or all of its original, posted target-ERP invoice. The approved credit is capped by the original invoice and returned quantity; it does not draw a second stock issue.
- Posting first reduces unpaid trade receivables (1200). Any remaining credit becomes customer refunds payable (2130), a distinct liability and subledger entry. It does **not** move cash or mark a refund paid. The original dispatch cost still controls restock and write-off.
- Rehearsal fingerprints the posted receipt claims and the receivable/liability split. Pending, unposted customer receipts hold return posting until they are posted or cancelled. A posted receipt cannot be reversed while a dependent posted target return exists.
- Sales Returns displays the proposed/posted refund liability and its aggregate. Invoice settlement reports `refund_due` when posted/approved receipts exceed the post-credit invoice balance.
- A synthetic invoice with a posted AED 6 receipt and two partial credits produces AED 13.95 total receivable reductions and an AED 6 refund liability. The liability is journal-balanced; no cash payout occurs.

## Still gated

- A governed customer-refund **disbursement** document, approval, bank evidence, cash posting and liability settlement are not yet implemented. The payable remains open. The next increment must prevent duplicate refund claims and support reversals and reconciliation.
- Pricing-only credit notes need a distinct no-stock adjustment document and tax/accounting controls. Selecting `pricing_correction` on a physical return remains blocked by the API.
- Staging posting remains disabled. PostgreSQL migration rehearsal, named UAT and production activation remain release gates. BizModo source data was not modified.
