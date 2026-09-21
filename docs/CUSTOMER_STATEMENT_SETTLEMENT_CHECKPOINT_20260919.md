# Customer statement and settlement checkpoint — 2026-09-19

This checkpoint adds calculated customer-invoice settlement status and an auditable customer statement. It does not modify BizModo evidence or enable permanent posting.

## Invoice settlement

Each approved target-ERP customer invoice now exposes:

- `Unpaid`: no approved receipt allocation exists.
- `Partially paid`: approved allocations are greater than zero but below the invoice total.
- `Paid`: approved allocations equal the invoice total.
- Paid amount, pending submitted allocation, outstanding amount and currently available outstanding.

Submitted receipt claims remain visible as pending and reserve the amount against double allocation, but they do not change the invoice to Paid until independent receipt approval.

## Customer statement

The Finance navigation now includes **Customer statements**. A statement combines:

1. the approved migrated opening receivable control;
2. approved target-ERP invoices up to the selected date; and
3. approved target-ERP customer receipts up to the selected date.

Historical BizModo invoice details are not added on top of the authoritative opening control, avoiding double counting. The statement displays debit, credit, running balance, document reference, source reference and status.

## Browser-test customer evidence

Customer: Al mas pack plastic trading

| Entry | Debit AED | Credit AED | Running balance AED |
|---|---:|---:|---:|
| Approved opening control | 84.00 | 0.00 | 84.00 |
| `SI-20260919-CFDC3419` | 10.50 | 0.00 | 94.50 |
| `CR-339EC1D6` | 0.00 | 10.50 | 84.00 |

The invoice is calculated as `Paid`: AED 10.50 paid, AED 0.00 pending and AED 0.00 outstanding. The statement closing balance remains AED 84.00 because the new invoice and approved receipt fully offset each other.

## Verification

- Focused receipt, settlement and statement tests: 13 passed.
- Full suite: 189 passed, 1 skipped.
- ERP preview health: `ok`.
- Statement `posting_enabled`: `false`.
- Permanent receipt/payment postings: zero.
- BizModo source writes: none.

The preview restart returns active browser sessions to the login page. After signing in, open **Customer invoices** to see settlement status or **Customer statements** to select the customer and statement date.
