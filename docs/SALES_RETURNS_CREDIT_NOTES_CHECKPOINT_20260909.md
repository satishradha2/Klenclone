# Sales Returns and Credit Notes Checkpoint — 2026-09-09

## Delivered

- Sales return draft creation and revision-protected editing.
- Required cloned customer and original sales-invoice relationship.
- Returned quantity split between saleable restock and controlled write-off.
- Mandatory disposition reason for written-off goods.
- UOM, conversion-factor, selling-price, VAT and cost snapshots.
- Maker-checker submit, cancel and independent approval workflow.
- One credit note generated per approved sales return.
- Posting rehearsal for AR, output VAT, sales returns, inventory, COGS and write-off expense.
- Only saleable returned quantity appears in the stock movement rehearsal.

## Safety state

- Credit notes and returns are approved but unposted.
- Permanent stock, AR and general-ledger posting remains disabled.
- BizModo is never written to by this workflow.
- Schema revision is `0011`.

## Verification

- Python and JavaScript syntax validation passed.
- Full automated suite: 104 passed, 1 intentionally skipped.
