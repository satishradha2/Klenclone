# Authenticated read-only UAT checkpoint

Date: 2026-09-09

## Outcome

An isolated authenticated UAT copy is available at `http://127.0.0.1:18082/#uat`. The normal SQLite control center remains at `http://127.0.0.1:8080/`, and the verified PostgreSQL clone remains at `http://127.0.0.1:18081/` with authentication disabled.

## Safety controls

- UAT login requires both `KLEN_AUTH_ENABLED=true` and `KLEN_UAT_AUTH_ENABLED=true`.
- Production mode rejects the synthetic UAT login flow.
- Only principals with `evidence.synthetic_uat=true` can sign in.
- Existing BizModo password material is not copied or used.
- Sessions use random opaque HttpOnly, SameSite=Strict cookies with server-side expiry and revocation.
- Logout requires a session CSRF token.
- Repeated login failures are rate limited.
- Password reset is a dry-run response and changes no password or business data.
- All non-authentication POST/PUT/PATCH/DELETE requests remain blocked with HTTP 405.
- At this historical checkpoint HRM was not yet exposed; HRM is now included in the target ERP through separately authorized workflows. Payroll remains excluded.

## Protected workspaces

The UAT reader has explicitly granted read-only access to customers, suppliers, products/UOM, sales, purchases, inventory movements, and an accounting summary. Transaction and inventory rows are filtered to the reader's active location scope. Contact email, telephone, address, tax number, raw payloads, and accounting detail are not exposed.

Pagination is capped at 200 rows per request, with 25 rows per page in the UI. Search inputs are length-limited and parameterized by SQLAlchemy.

## Verification

- Unit/API suite: 52 passed, 1 PostgreSQL-only test skipped outside its isolated profile.
- Reproducible authenticated technical UAT: 82 checks passed, 0 failed.
- Browser: synthetic login succeeded; customers, sales, and inventory rendered; one-location identity was visible; logout returned to the sign-in form.
- API denial checks: unauthenticated protected request returned 401; attempted business POST returned 405.
- Original SQLite source SHA-256 before and after UAT preparation: `1bbaab2abdd0c51481747e5956098e61f67da1cd603bb735a48d704a56c42c62`.
- Original SQLite last-modified time remained `2026-09-08T19:10:44.1899220Z`.

## Boundary

`var/klen_uat_validation.db` is a separate validation copy with one synthetic principal and read grants. It is not a migration truth source and must never replace the verified clone. Human UAT users remain unprovisioned pending the assignment and approval sheet.

The formal discrepancy register contains 188 open source-data exceptions: 90 finance/accounting, 61 inventory/UOM, and 37 transaction/master relationships. These remain blocked and were not auto-corrected.
