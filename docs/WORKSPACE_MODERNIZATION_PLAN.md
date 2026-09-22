# Adaptive workspace migration

Existing architecture: FastAPI serves a static HTML shell; hash routes dispatch
domain JavaScript renderers. Auth/session supplies permissions and CSRF tokens.
Domain APIs own transactions, approval, calculations and audit evidence.

Migration order:
1. Add isolated shell tokens, user preferences and keyboard page navigation.
2. Consolidate permission metadata against backend endpoint checks before adding
   record search, role dashboards or aggregated approvals.
3. Migrate tables and forms incrementally, retaining server pagination and state.
4. Add record inspectors and attention queues using authorized backend data.
5. Introduce AI contracts only with explicit unavailable states until connected.

Verification gates: syntax and existing workflow regression tests; keyboard
navigation, focus restoration, restricted-role visibility, responsive layout,
theme contrast and persisted settings. Browser acceptance is separate from
passing backend tests. Payroll remains excluded. Warehouse implementation is
paused during this frontend migration; existing changes are retained.

The supplied brief ends mid-sentence in section 36. No unseen requirements are
assumed. This plan covers the provided requirements progressively; shell delivery
does not represent completion of tables, approvals, notifications or AI services.

## Browser verification — 21 September 2026

Verified against the rebuilt local preview at port 18082, signed in by the user.
Only navigation and presentation preferences were exercised; no commercial
documents, approvals, stock or accounting records were changed by browser QA.

- Overview and Sales orders load with the shared shell.
- Ctrl+K opens the command centre; filtering and Enter navigate to Sales orders.
- ArrowUp from search focuses the last result; Escape closes and restores focus
  to the command trigger. Recent pages are ordered newest first.
- Unknown page searches display an explicit empty state.
- Light, dark, system and high-contrast controls were exercised. Dark sales form
  fields now render light text on a dark surface rather than white on white.
- Compact and dense modes work; dense table cells use 5px vertical padding.
- Density and collapsed navigation survive reload. Accessible button labels
  include the current preference, and icon navigation retains page names.
- A 390px-wide mobile check confirmed collapsible navigation, readable sales
  fields and no document-level horizontal overflow. Viewport override was reset;
  theme was restored to system, density to comfortable and rail to expanded.
- No browser console errors were reported during the final pass.

Browser findings corrected: detached header title; dark form specificity;
low-contrast active navigation icons; undersized commercial buttons; keyboard
wraparound; recent sorting; invalid stored preference values; asset cache versions.

Automated shell checks: `node --test tests/js/workspace-shell.test.cjs` (4 passed).
Focused ERP checks: `python -m pytest tests/test_erp_preview.py -k
'workspace_assets or independent_read_only' -q` (4 passed, 37 deselected).
Full Python regression: `python -m pytest -q` (244 passed, 1 skipped in 261.30s).
The skipped integration test is not counted as production acceptance.

Remaining acceptance scope: restricted-role browser matrix (the command centre
inherits existing navigation visibility, which still needs complete permission
metadata); theme coverage across every legacy module; business UAT; favorites,
aggregated approvals, record inspectors and AI integrations. This pass is not a
claim of full modernization or production readiness.

## Permission-aware navigation increment

The authenticated session now returns a versioned, server-owned list of denied
routes derived from effective permissions. The sidebar, direct hash router and
command centre consume the same result; inaccessible routes are hidden, empty
navigation groups collapse, and a manually entered restricted hash renders an
access-restricted state without calling that workspace API. Backend endpoint
permission checks remain authoritative for data and mutations.

The audit also found that commercial-pricing and warehouse-control mutations
were absent from the preview safety middleware allowlist. Both prefixes are now
recognized as controlled operational workflows and continue through their CSRF,
permission, scope and maker-checker checks. They remain non-posting. A quality
controller can now read the warehouse-control workspace through either count or
quarantine responsibilities, and the active quarantine count is location scoped.

Automated coverage verifies a restricted quality role, denied route metadata,
direct-router enforcement wiring, quarantine-only workspace access, and that
warehouse/pricing POSTs are no longer rejected with HTTP 405 before their domain
guards. Finance navigation is also aligned with the read APIs for accounting,
chart of accounts, general ledger, ageing, customer statements and credit control;
a company-wide financial-report reader is covered independently. A full
restricted-role browser matrix still requires purpose-provisioned UAT identities
and remains an acceptance gate rather than an inferred success.

## My Workspace approval inbox increment

The shell now includes a centralized, read-only approval inbox backed by a
server-owned registry of operating-unit, commercial-pricing, sales, purchasing,
warehouse, HR, cash, expense, tax, close, reporting, credit and finance approval
states. The API returns only workflows covered by the signed-in user's effective
permissions and only records inside their allowed location scope.

Entries created or submitted by the current user remain visible but are marked
as requiring an independent approver. The inbox never decides or posts a record;
it deep-links to the owning workspace, where existing CSRF, permission, scope,
revision and maker-checker controls remain authoritative. Automated coverage
verifies authentication, shell registration, permission filtering, location
filtering and self-approval exclusion.

## Warehouse serial and barcode traceability increment

The non-posting warehouse workspace now supports globally unique barcode and
serial identities tied to controlled SKU, UOM and location data. Barcode
registration preserves an explicit factor-to-base snapshot; serial registration
cannot exceed controlled on-hand quantity. Barcode/serial collisions, duplicates,
unknown identities and wrong-location serial scans are rejected or recorded as
blocked evidence rather than silently accepted.

Every scan is retained in a location-scoped audit trail. Quarantined and retired
serials are blocked at scan time. Serial quarantine, release and retirement use
revision checks, and the user who quarantined a serial cannot release it. Pending
serial releases are surfaced in My Workspace but remain routed to the warehouse
workspace, where permission, location and maker-checker controls are authoritative.
No stock quantity, source export, accounting balance or posting state is changed.

Automated verification: JavaScript shell checks pass 4/4; the complete Python
regression passes 247 tests with 1 skipped. The skip remains an external
integration acceptance item and is not counted as production readiness.

## Central record inspector and attention center increment

The shared workspace framework now makes meaningful data rows keyboard-focusable
and opens one consistent, read-only record inspector across centrally migrated
pages. The inspector derives its field labels and values only from the table data
already rendered for the signed-in user. It exposes no save, approval, posting or
workflow mutation and leaves every controlled action in the owning workspace.

The header now also provides a centralized attention center. It combines the
permission- and location-filtered My Workspace approval inbox with visible
exception, blocked, pending, overdue and review signals from the current page.
Self-submitted items remain explicitly separated as awaiting an independent
approver. Selecting an approval navigates to its owning workspace; the center
does not decide or mutate it.

The drawer layouts support desktop and 390px mobile widths, native dialog focus
containment, row activation by pointer or keyboard, and text-only DOM rendering.
Automated contracts verify that the central script performs only the authenticated
GET for `/api/v1/my-workspace`, contains no mutation method or CSRF path, and is
wired through the central shell and migration layer. Verification for this
increment: 23/23 JavaScript tests, focused preview tests 3/3, and the complete
Python regression 248 passed with 1 skipped. The skip remains an external
integration acceptance item and is not counted as production readiness.

## Authentication surface visual migration

The pre-authentication page is now part of the same visual system as the ERP
shell. Its green legacy presentation was replaced with the shared navy, blue,
amber and neutral design tokens, a clearer access hierarchy, explicit source,
scope and posting assurances, visible focus treatment and responsive desktop,
tablet and mobile layouts. The username and password names, browser autocomplete,
login endpoint, session check, redirect behavior and authentication controls are
unchanged.

Automated verification covers both the responsive visual contract and the
unchanged `/api/v1/auth/login` integration. Browser acceptance is performed at
desktop and 390px widths after rebuilding the read-only preview image.
