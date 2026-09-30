# Cross-border synthetic end-to-end verification (2026-09-29)

## Scope and isolation

The cross-border API scenario creates clearly synthetic Saudi/SAR and Kuwait/KWD customers, price groups/lists, commercial FX references, provisional trade decisions, quotations, order releases, credit profiles, warehouse stock, delivery-readiness and dispatch decisions, POD, export-evidence files, tax reviews, and held invoice drafts. It runs against isolated SQLite clone/operational fixtures under `var/cross-border-browser-uat-20260929/`, not the shared port 18082 operational database or BizModo. The PDF bytes are minimal test fixtures and **not** genuine customs, transport, or tax evidence.

The browser check used a separate loopback-only preview on port 18083 and the synthetic Kuwait fixture. It showed the quotation and order-release registers, delivery-readiness and consumed dispatch release, delivered/POD control board, consumed export-tax review with evidence links, and a KWD 2.467 held invoice draft with an AED 2.42 approved commercial-rate reference. The invoice-table compression found during this check was corrected with explicit column widths and wrapping; delivery wording was corrected to distinguish a permitted held draft from blocked issuance.

## Automated outcomes

- Authenticated API scenario passed for both SAR and three-decimal KWD. It rejects missing/incorrect tax and approvals, maker self-approval, premature allocation/dispatch/invoice, and foreign invoice submission.
- After the synthetic draft, the API returns the approved exact-date FX reference, keeps settlement `not_released`, exposes no invoice open item for receipt allocation, and records exactly one operational dispatch stock movement with zero payment, journal, or integrated posting batches.
- Full local Python regression suite rerun after the PostgreSQL test hook: **292 passed, 1 skipped**. Focused cross-border/FX tests passed after the final assertion change. Frontend suite: **37 passed** after replacing three stale stylesheet-version assertions and adding a held-invoice readability regression check. JavaScript syntax and `git diff --check` passed.
- An existing canonical-clone PostgreSQL integration test passed in a newly migrated isolated database, `klen_validation_20260929`. This verifies clone migration, RBAC/location scope, and read-only behavior.
- The authenticated cross-border scenario also passed for SAR and KWD against separate PostgreSQL operational validation databases, `klen_cross_border_sa_20260929` and `klen_cross_border_kw_20260929` (**2 passed**). The existing test accepts an opt-in `KLEN_TEST_OPERATIONAL_DATABASE_URL_TEMPLATE` with a `{country}` placeholder; ordinary runs still use isolated SQLite. Use fresh, isolated databases for a repeat run because the scenario intentionally creates the commercial and workflow records.
- Read-only SQL verification in each PostgreSQL fixture found one quotation, order, delivery, held invoice, export-review decision, and dispatch stock movement, with **zero** journal batches. The records are synthetic and remain confined to the two validation databases.
- The shared preview on port 18082 and BizModo source were not used for synthetic record creation.
- The changed stylesheet and delivery module have new cache keys in the shared preview shell, so a browser reload retrieves the corrected presentation.
- The rebuilt shared preview returned healthy clone and operational databases, authentication enabled, and `posting_enabled=false`; both new static cache keys were served.

## Still open

Synthetic files prove workflow mechanics, not document authenticity, physical export, legal zero-rating, tax timing, named business-user acceptance, or production readiness. The operational PostgreSQL workflow and an isolated migration/restore rehearsal are now tested, but a production-target backup/restore, genuine document-level tax review, warehouse/finance UAT, final source-data reconciliation, production infrastructure, and cutover approval remain separate gates. Foreign invoice submission, issuance, settlement, realized FX accounting, permanent posting and production activation remain disabled. These controls must not be enabled merely because the synthetic workflow tests pass.

There are no historical foreign sales or purchases in the BizModo source scope. Foreign-trade tax/evidence/UAT requirements are gates for **future foreign-trade activation**, not blockers for accepting domestic AED workflows. The domestic release has its own cutover gates, recorded in `DOMESTIC_RELEASE_AND_FUTURE_TRADE_GATES_20260929.md`.
