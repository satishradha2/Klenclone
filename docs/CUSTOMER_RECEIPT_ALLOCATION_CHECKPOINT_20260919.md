# Customer receipt allocation checkpoint — 2026-09-19

This checkpoint validates the controlled customer-receipt path against a target-ERP invoice. All amounts and documents are test evidence only. Permanent posting and production activation remain disabled.

## Verified flow

1. Customer invoice `SI-20260919-CFDC3419`, backed by delivery note `DN-C69CBD59` and proof of delivery `POD-BROWSER-20260919-001`, was available as an open receivable for Al mas pack plastic trading.
2. Maker `asas-admin` created cash receipt `CR-339EC1D6` for AED 10.50 and allocated the full amount to the invoice.
3. Submission created one active AED 10.50 allocation claim and reduced the invoice's available open amount to zero without posting accounting.
4. Independent checker `asas-approver` approved revision 3.
5. The posting rehearsal was persisted and displayed as `BALANCED REHEARSAL`.

## Accounting rehearsal

| Account | Debit AED | Credit AED |
|---|---:|---:|
| Cash - AED | 10.50 | 0.00 |
| Accounts Receivable | 0.00 | 10.50 |
| **Total** | **10.50** | **10.50** |

The customer subledger rehearsal contains one AED 10.50 receipt entry linked to `SI-20260919-CFDC3419`. The stored reversal is exact: debit Accounts Receivable AED 10.50 and credit Cash - AED AED 10.50, with a negative AED 10.50 subledger entry.

## Control evidence

- Receipt status: `approved`
- Receipt revision: `3`
- Active allocation claims: `1`, AED 10.50
- Receipt posting rehearsals: `1`
- Posted receipts/payments: `0`
- Permanent operational journal batches: `0`
- Rehearsal `posting_enabled`: `false`
- BizModo source writes: none

The browser-validated AR ageing row for Al mas pack plastic trading separately reports AED 10.50 as approved-unposted activity. The new AED 10.50 invoice and matching receipt net to zero, so the authoritative pre-existing opening exposure remains AED 84.00 and the row stays reconciled.

The downstream settlement calculation marks invoice `SI-20260919-CFDC3419` as `Paid`, with AED 10.50 paid and AED 0.00 outstanding.

## Frontend correction

The payment workspace previously referenced an undefined `mutate` helper for submit, approve, cancel and rehearsal actions. It now owns a scoped `paymentMutation` request helper, uses a new cache version, and has a regression assertion preventing recurrence.

## Remaining production gate

This evidence does not authorize permanent receipt posting. Final production activation still requires the agreed full test-data purge, fresh complete BizModo import, reconciliation, opening-balance approval, security/UAT acceptance and explicit posting enablement.
