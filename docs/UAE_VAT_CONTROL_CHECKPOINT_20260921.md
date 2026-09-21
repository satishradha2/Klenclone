# UAE VAT control checkpoint — 2026-09-21

## Scope

This checkpoint adds a target-ERP UAE VAT control centre. It does not amend BizModo evidence, submit a tax return to the FTA, or post accounting entries.

## Controlled workflow

1. A maker opens a VAT period with the company TRN, reporting dates and return due date.
2. The workspace derives output and input VAT from approved target-ERP customer invoices, sales credit notes, validated supplier tax invoices, purchase debit notes and eligible expense tax invoices.
3. Reverse-charge and correction adjustments require evidence, a reason and independent approval.
4. Submission freezes the source rows and their fingerprint. Pending adjustments prevent submission.
5. An independent approver approves or rejects the frozen return.
6. An approved return can produce a fingerprint-idempotent, balanced settlement rehearsal. Filing and permanent posting remain disabled.

## Accounting rehearsal

The rehearsal clears output VAT and input VAT into either FTA VAT payable or FTA VAT receivable. It is evidence for testing only: `posting_enabled`, `posting_performed`, and `filing_performed` are always false.

## Production boundary

At final cutover, test rows will be deleted and the complete BizModo dataset freshly imported into the target ERP. The source system remains read-only throughout extraction and validation. Production filing needs a separately approved FTA integration, credentials, filing acknowledgement handling and cutover sign-off.
