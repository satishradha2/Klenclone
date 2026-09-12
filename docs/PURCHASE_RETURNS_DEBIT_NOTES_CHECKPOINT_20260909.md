# Purchase Returns and Debit Notes Checkpoint — 2026-09-09

## Delivered

- Draft purchase return creation and revision-protected editing.
- Source validation against an accepted operational GRN or cloned supplier purchase invoice.
- Per-SKU source quantity cap and cumulative prior-return protection.
- Outgoing stock reservation on submission and release on cancellation.
- Separate supplier-return and internal write-off disposition quantities.
- Mandatory reason for internally written-off quantity.
- Maker-checker approval and one debit note per approved purchase return.
- AP, input VAT, inventory, write-off and purchase-return variance rehearsal.
- Deterministic posting fingerprint with permanent posting disabled.

## Safety state

- No stock quantity, AP balance, VAT ledger or general-ledger balance is posted.
- BizModo remains read-only.
- Existing operational data is preserved.
- Schema revision is `0012`.

## Verification

- Python and JavaScript syntax validation passed.
- Full automated suite: 108 passed, 1 intentionally skipped.
