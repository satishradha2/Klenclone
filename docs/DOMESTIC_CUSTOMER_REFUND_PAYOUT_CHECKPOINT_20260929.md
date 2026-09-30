# Domestic customer-refund payout checkpoint — 2026-09-29

> Historical payout-only checkpoint. The later combined pricing-credit and recovery implementation is described in [DOMESTIC_CUSTOMER_CREDIT_REFUND_WORKFLOW_20260929.md](DOMESTIC_CUSTOMER_CREDIT_REFUND_WORKFLOW_20260929.md).

## Implemented

- A posted target-ERP sales credit note can fund one or more partial AED refund requests, limited to the posted 2130 customer-refund liability. Submitted, approved, and posted requests reserve that liability; drafts do not.
- Refund requests are revision-checked and audited. The maker cannot approve their own refund. The approved bank account must be active, AED-denominated, and in the permitted location.
- Payout posting requires an imported bank-statement debit matched one-to-one to the approved refund, the exact amount, account, and date, plus independent approval of that reconciliation. The bank date must fall in an open fiscal period.
- The balanced journal debits customer-refund payable (2130) and credits the selected bank account's GL. Atomic posting uses a fingerprinted idempotency key; a replay does not pay twice.
- Posted payouts reduce outstanding refund liability and appear in invoice settlement and customer statements. A posted bank-confirmed refund blocks reversal of its source return. It cannot be erased with a journal reversal; recovery requires a distinct compensating receipt workflow.
- The Sales Returns workspace now has a linked refund form, approval queue, bank-debit match, journal preview, and a gated posting action. Bank-statement import and independent approval remain in Bank & Cash.

## Deliberate limits

- The staging environment still has global posting disabled. A rehearsal and synthetic test do not release money or constitute production acceptance.
- A no-stock pricing-only credit/correction document is not part of this payout increment. Sales returns explicitly reject pricing corrections; that separate controlled document remains to be built.
- A compensating customer receipt for a disputed payout is not yet built. Posted bank evidence is retained rather than silently reversed.
- BizModo source records and credentials are not changed.
