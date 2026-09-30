# Target-ERP sales-return posting checkpoint (29 September 2026)

## Implemented

- Return draft preparation uses the original delivery-dispatch unit cost, not today's stock average. Submission rejects changed issue-cost, UOM, quantity factor, price or VAT evidence.
- A target return can rehearse and enter the governed integrated-posting route only when its original customer invoice and accounting batch are posted. Rehearsal rechecks invoice identity, priced credit, receipts, earlier return sequence and original issue value. Partial-return cost cents are allocated cumulatively, conserving the original dispatch value.
- Posting debits sales returns and output VAT, credits receivables, and either restocks at original cost or reclassifies written-off cost. It creates a customer-invoice-linked negative receivable subledger entry. Rehearsal and posting are fingerprinted; posting revalidates evidence under locks.
- Return reversal is blocked by a locked fiscal period, later active target returns, later receipt allocations or stock activity that prevents exact reversal. A synthetic two-part return with restock and write-off was posted and reversed in safe order, followed by original-invoice reversal.
- The Sales Returns page exposes rehearsal when the original invoice is posted, and exposes posting/reversal only when global posting activation and permissions allow it. Current staging remains non-posting.
- Target-invoice return creation no longer depends on a BizModo clone snapshot when operational location masters exist; the legacy source-invoice return path still requires its immutable snapshot. An API test covers the target-only configuration.

## Still gated

- A credit beyond unpaid receivables now posts the excess to a customer-refund liability, with no cash disbursement. See [customer-refund liability checkpoint](DOMESTIC_CUSTOMER_REFUND_LIABILITY_CHECKPOINT_20260929.md). Governed payout and pricing-only adjustments remain separate work.
- Old approved target returns containing a present-day cost rather than the original issue cost cannot be posted until reviewed. Legacy dispatches without genuine cost evidence remain held.
- The operational PostgreSQL `0065` migration, a real database rehearsal, named UAT and production activation remain separate release gates. BizModo data was not changed.
