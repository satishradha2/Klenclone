# Clone-to-Operational Promotion Policy — 2026-09-09

## Required end state

The immutable BizModo clone is migration evidence, not the final operating store. At the final controlled cutover, every in-scope cloned record must be represented in the operational ERP or listed in an approved exception register.

## Promotion rules

1. Keep the raw and canonical clone immutable for audit and reconciliation.
2. Promote records into operational masters, subledgers, stock ledgers and document histories.
3. Record a one-to-one lineage key and source checksum for every promoted record.
4. Reject duplicate source identities and duplicate operational identities at database level.
5. Reconcile record counts, control totals, AR/AP, inventory quantity/value and journal balances before activation.
6. Carry original BizModo document numbers, dates and counterparties as source references.
7. Run all future actions through ERP permissions, fiscal periods, maker-checker and posting/reversal controls.

## Edit, deactivate and delete semantics

- Active operational masters can be edited and deactivated, with revisions and audit history.
- Inactive masters can be reactivated or corrected.
- A never-used ERP-created master can be deleted before it is referenced.
- A promoted or referenced master is deactivated, not physically erased.
- Unposted draft transactions can be edited, cancelled or deleted.
- Posted transactions and imported historical documents are never overwritten or physically deleted. Corrections use reversal, credit/debit notes or controlled adjustment documents.

These rules preserve accounting, VAT, stock valuation and audit continuity while still allowing the migrated data to operate normally in the new ERP.

## Activation gates

- Final source capture and checksums verified.
- Every in-scope row promoted or covered by an approved exception.
- All source-to-operational control totals reconciled.
- Promotion approved by an independent reviewer.
- Posting enabled only after the final cutover decision.

Schema revision `0010` contains the promotion batches, one-to-one lineage registry and exception registry. No promotion has been executed yet.
