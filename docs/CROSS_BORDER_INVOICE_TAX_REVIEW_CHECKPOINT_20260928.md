# Cross-border invoice tax review checkpoint (2026-09-28)

This is a controlled staging increment after approved physical dispatch and proof of delivery. It creates a non-posting **foreign invoice draft**, not a released/issued invoice, approved receivable, settlement claim, or accounting posting.

## Path and controls

1. A delivered foreign fulfillment must have a consumed, independently approved physical dispatch release. Shipment references alone never qualify as proof of export.
2. A tax maker attaches immutable PDF/PNG/JPEG files to the delivery and proposes zero-rated or standard-rated treatment with a written basis and validity date. Each file is capped at 2 MiB, stored in the operational database, and SHA-256 checked when reviewed/downloaded/used.
3. Zero-rated proposals require either a customs declaration plus commercial transport evidence, or a shipping certificate plus official exit evidence. Standard-rated proposals require a tax memo. These file categories are a workflow precheck, not automatic evidence verification or legal determination. A separate authorized reviewer must inspect the actual files and record a detailed decision.
   Customs-suspension and other special treatments are deliberately held for a separately reviewed policy, rather than forced into either automated branch.
4. The final rate must match the already approved quotation/order line rate. A mismatch stays held for a controlled commercial revision; the invoice creator cannot silently substitute tax. Approval is tied to the delivery/POD, order totals, destination, currency, quantities and revision fingerprint, and expires. Maker, delivery maker, order maker and quotation maker cannot approve.
5. A current approved decision permits a single non-posting draft with delivered quantities and currency-specific amount precision. The decision is consumed and linked to the draft. Foreign draft submission/approval, customer-receipt settlement and accounting rehearsal remain held.

The UAE Federal Tax Authority's [VATP040 clarification](https://tax.gov.ae/Datafolder/Files/Pdf/2025/VATP040%20-%20Amendments%20to%20VAT%20ER%20-%2014%2003%202025.pdf) describes evidence combinations for zero-rating exports of goods. The tax owner still needs to assess actual evidence, supply conditions and policy; the software does not infer 0% VAT from the destination or file labels.

## Release gates still open

- Named business-user UAT using actual representative export evidence, including authenticity, readability and line/order matching.
- Tax-policy owner acceptance of VAT treatment and invoice timing, plus settlement/FX and receivable controls for foreign currencies.
- Foreign invoice submission, approval, issuance and accounting posting remain disabled; production activation remains disabled.
- BizModo source remains read-only. All records in this increment are in the clone's operational database.
