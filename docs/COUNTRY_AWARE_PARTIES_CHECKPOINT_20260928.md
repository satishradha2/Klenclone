# Country-aware customer and supplier masters — staging checkpoint

Target-side party requests now capture a validated ISO country, preferred ISO currency, and optional tax ID with registration type and issuing country. Independent approval, duplicate checks, source read-only access, and audit events remain in force. Existing promoted parties retain `NULL` country/currency rather than being silently classified as UAE.

The Customers and Suppliers registers show country, currency, and UAE/GCC/international classification. The same in-context creation modal is available from Sales Quotation and Procurement; an unfinished document is not discarded. The preferred currency is a master-data preference only, **not** a transaction currency or an exchange rate.

Cross-border transaction execution is not enabled by this increment. Newly approved non-UAE target parties are excluded from domestic transaction and van-route selectors. Shared draft/quotation validation, supplier sourcing, van-route planning, and goods-receipt preparation reject direct submission by code. Source-promoted parties with unverified country preserve their pre-existing staging behavior until verified; they are not asserted to be UAE parties.

Before enabling GCC sales or international purchasing, build and validate transaction currency/FX-rate snapshots, country-specific tax decisions and evidence, import/export and landed-cost rules, and business-user acceptance. Do not infer a tax rate or export treatment solely from the party's country or tax ID.

Validation on 2026-09-28: the full automated suite passed (274 passed, 1 skipped); the latest focused party, van-sales, and goods-receipt tests passed (11 passed). The rebuilt preview returned healthy with posting disabled, and its operational PostgreSQL tables contain all four new party fields. In the signed-in browser, supplier and customer request forms opened; AE suggested AED, BH suggested BHD, SA suggested SAR, and IN displayed the international transaction hold. No browser test party was submitted. Named business-user acceptance remains outstanding.
