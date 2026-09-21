# Supplier tax-document and AP posting-rehearsal checkpoint

Date: 2026-09-15

## Outcome

The target ERP now validates a separately stored supplier tax-document record before a supplier invoice can pass three-way matching. The captured record includes the document type, issue and supply dates, supplier and recipient identities and addresses, supplier and recipient TRNs, AED line values, VAT rates, VAT amount, and document total.

Validation applies the current Federal Tax Authority invoice particulars used by this checkpoint:

- a taxable document must be identified as a tax invoice;
- supplier and VAT-registered recipient TRNs must contain exactly 15 digits;
- the invoice must be issued on or within 14 days after the supply date;
- a simplified tax invoice for a VAT-registered recipient cannot exceed AED 10,000;
- a supplier TRN that conflicts with the governed supplier master is a hard exception;
- where the imported supplier master has no valid TRN, the structurally valid document is retained with an explicit final-cutover master-review note rather than altering source data.

References: Federal Tax Authority, [Tax invoices](https://tax.gov.ae/Datafolder/Files/Pdf/2023/Knowledge%20Center%20Page/VAT11%20-%20Tax%20invoices%20En.pdf) and [Tax Invoices guide](https://tax.gov.ae/DataFolder/Files/Pdf/06-Tax-Invoices.pdf).

## Non-posting accounting rehearsal

An approved, matched invoice with passed tax validation can generate an idempotent accounting rehearsal for an open rehearsal-enabled fiscal period:

- debit Goods Received Not Invoiced for the invoice net amount;
- debit Input VAT Recoverable for the VAT amount;
- credit Trade Payables for the gross amount.

The ERP verifies that total debits equal total credits, stores a deterministic fingerprint, and generates the exact reverse journal in reverse order. Repeating the same invoice-revision rehearsal returns the existing plan rather than creating a duplicate.

The rehearsal does not create a payable, VAT ledger entry, GRNI clearing entry, journal batch, inventory movement, payment, or reversal. `posting_enabled` is fixed to false.

## Data boundary

BizModo remains strictly read-only. Tax-document values entered here are target-ERP test records only. They do not correct or back-write imported supplier masters. All target test data remains subject to the separately authorized full purge before the final fresh BizModo import.

## Remaining gates

- finance and tax-owner approval of final production account mappings and company/supplier TRNs;
- accredited UAE e-invoicing service-provider selection and structured-document integration;
- atomic production posting implementation for approved supplier invoices and approved adjustments;
- controlled reversal execution, later-activity protection, named-user UAT, and cutover approval.
