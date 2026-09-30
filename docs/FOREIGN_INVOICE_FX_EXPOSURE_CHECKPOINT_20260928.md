# Foreign invoice FX exposure checkpoint (2026-09-28)

The Customer Invoices control board now shows a read-only AED reference for a held foreign-currency invoice draft. It uses only an independently approved commercial FX rate for the **exact invoice date** and rounds the resulting AED reference to two decimals. If that rate is missing or pending, the board says so rather than silently applying a prior-day or unapproved rate. An AED-denominated foreign draft needs no FX rate but remains held. The original invoice amount and currency are unchanged.

This is exposure visibility, **not** a receivable, VAT conversion, payment allocation, realized FX gain/loss, settlement authorization, or journal. Foreign invoice submission, approval, settlement, and accounting release remain blocked. The existing AED-only payment engine is not reused for foreign amounts.

The representative cross-border UAT is still open: staging has no eligible foreign delivery or actual export documents for a named tax reviewer to inspect. Tax-policy owner acceptance of evidence and invoice timing, plus foreign-currency settlement design and business-user UAT, remain release gates. BizModo remains read-only and production posting disabled.
