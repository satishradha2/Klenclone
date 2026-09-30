# GCC three-decimal quotation checkpoint

Date: 2026-09-28

The Sales Orders quotation path now supports BHD, KWD, and OMR at three
minor-unit digits, alongside AED, USD, EUR, GBP, SAR, and QAR at two. The
currency list and precision come from one target-side server catalogue and
are returned to the Sales Orders workspace. This catalogue is deliberately
narrower than the party-master currency list.

Quotation line net, discount, provisional tax, gross, and header totals are
calculated at the selected currency's minor unit. The approved price-list
discount ceiling uses the same unit. The approved commercial FX reference
still produces a separately rounded **two-decimal AED reference snapshot**.
The operational PostgreSQL schema widens quotation amounts to NUMERIC(19,3)
through additive migration 0058 without rewriting existing amounts.

This is a **non-posting quotation capability only**. The provisional tax and
trade decision is not final invoice treatment or proof of export. Conversion
to an international sales order stays blocked until order-stage trade/tax,
foreign-currency credit, delivery, invoicing, and settlement controls are
released. BizModo source data remains read-only.

Currency minor-unit design was cross-checked on 2026-09-28 against the ISO
4217 Maintenance Agency's current List One:
https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html

Focused tests cover BHD, KWD, and OMR persistence and arithmetic, rejection
of excess precision for AED and foreign quotations, the approved price-list
ceiling, AED FX snapshot rounding, and the authenticated HTTP quotation path.
The full test suite passed with 290 tests and 1 optional skip. The rebuilt
local preview is healthy with both databases reachable and posting disabled;
PostgreSQL migration 0058 is present and the quotation total and line-discount
columns report scale 3. Named business-user acceptance and an authenticated
browser walkthrough remain separate release gates.
