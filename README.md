# Klen Clone

This workspace is for the read-only reconstruction of the BizModo V7.5.1 application used by Asas General Trading LLC and its evolution into an enterprise ERP.

## Non-negotiable source rule

The live BizModo system is read-only for this project. No source record, user, permission, setting, status, transaction, attachment, or configuration may be created, edited, approved, cancelled, assigned, imported, or deleted.

All extracted files are immutable source evidence. Cleaning, normalization, correction, and transformation occur only in derived staging datasets and the new ERP database, with an audit trail back to the source record.

## Current scope

- Sales and POS
- Purchasing
- Products and inventory
- Customers and suppliers
- Expenses, payment accounts, accounting, and reports
- Delivery, field force, routing, and zones
- CRM
- HRM included in the target ERP; payroll excluded
- Settings, roles, permissions, notifications, and integrations

Raw exports are excluded from source control because they contain confidential company and personal data.

## Current artifacts

- `docs/ERP_COMPLETION_AUDIT_CHECKPOINT_20260921.md` — current route-backed staging coverage and the explicit remaining capability register; prevents permissions or source evidence from being misreported as implemented modules.
- `docs/COMPLETE_HRM_LIFECYCLE_CHECKPOINT_20260921.md` — recruitment, candidate pipeline, employee documents and expiry, onboarding, performance, training, disciplinary, separation and end-of-service controls with payroll excluded.
- `docs/SOURCE_SYSTEM_INVENTORY.md` — module and record inventory.
- `docs/EXPORT_MANIFEST.md` — immutable evidence manifest and hashes.
- `docs/DATA_RECONCILIATION.md` — counts, balances, variances and cutover gates.
- `docs/LOGIC_DEFECT_REGISTER.md` — source defects and safe clone treatment.
- `docs/STAGING_DATA_MODEL.md` — no-loss staging and provenance design.
- `docs/IMPORT_CHECKPOINT.md` — immutable raw-import verification.
- `docs/TRANSFORMATION_CHECKPOINT.md` — typed staging and relationship controls.
- `docs/RELATIONSHIP_RECONCILIATION.md` — identity resolution and per-document results.
- `docs/INVENTORY_UOM_CHECKPOINT.md` — canonical UOM controls and reconstructed stock movements.
- `docs/FINANCIAL_ALLOCATION_CHECKPOINT.md` — VAT, discount, rounding, return, payment and due allocation controls.
- `docs/ACCOUNTING_LEDGER_CHECKPOINT.md` — cash-flow ledger, payment links, VAT, AR/AP and trial-balance controls.
- `docs/COA_JOURNAL_OPENING_CHECKPOINT.md` — provisional chart of accounts, balanced journal blueprints and inventory-opening controls.
- `docs/FINANCE_RECONCILIATION_WORKFLOW_CHECKPOINT_20260915.md` — maker/approver review plans for test-data trial-balance and opening AR/AP variances without clearing source exceptions or enabling posting.
- `docs/GENERAL_LEDGER_TEST_WORKSPACE_CHECKPOINT_20260915.md` — balanced manual journal plans, approval workflow, account drill-down and projected financial statements with posting disabled.
- `docs/HRM_TEST_WORKSPACE_CHECKPOINT_20260915.md` — privacy-controlled employee, attendance and shift test-data workspace with payroll explicitly excluded.
- `docs/ENTERPRISE_PROCUREMENT_CHECKPOINT_20260915.md` — location-scoped requisition, RFQ, supplier-quotation comparison, award and purchase-order approval controls with posting disabled.
- `docs/PROCUREMENT_THREE_WAY_MATCH_CHECKPOINT_20260915.md` — approved PO receipt binding and supplier-invoice three-way matching with exception blocking and no AP/ledger posting.
- `docs/PROCUREMENT_TOLERANCE_ADJUSTMENT_CHECKPOINT_20260915.md` — independently governed match tolerances and supplier credit/debit notes linked to approved invoices, with posting disabled.
- `docs/SUPPLIER_TAX_AND_POSTING_REHEARSAL_CHECKPOINT_20260915.md` — UAE supplier tax-document validation plus balanced, idempotent GRNI/Input VAT/AP and reversal rehearsals with no posting.
- `docs/SUPPLIER_INVOICE_ATOMIC_POSTING_CHECKPOINT_20260919.md` — activation-gated atomic AP/Input VAT/GRNI posting, payable subledger creation, idempotency and dependency-safe exact reversal.
- `docs/SUPPLIER_ADJUSTMENT_ATOMIC_POSTING_CHECKPOINT_20260919.md` — supplier credit/debit-note accounting treatments, duplicate purchase-return protection, atomic payable/VAT posting and dependency-safe reversal.
- `docs/PURCHASE_RETURN_ATOMIC_POSTING_CHECKPOINT_20260919.md` — posted-invoice-linked purchase returns, persisted rehearsal evidence, atomic stock/AP/VAT/subledger posting and exact reversal controls.
- `docs/SALES_RETURN_ATOMIC_POSTING_CHECKPOINT_20260919.md` — immutable original-invoice evidence, cumulative credit caps, atomic AR/Output VAT/inventory/subledger posting and dependency-safe exact reversal.
- `docs/SALES_INVOICE_ATOMIC_POSTING_CHECKPOINT_20260919.md` — reservation-backed sales-invoice rehearsal, atomic AR/Output VAT/COGS/inventory posting, idempotency and dependency-safe exact reversal.
- `docs/CUSTOMER_RECEIPT_ALLOCATION_CHECKPOINT_20260919.md` — approved POD-backed invoice collection, controlled allocation claim, independent approval, balanced cash/AR rehearsal and exact reversal.
- `docs/CUSTOMER_STATEMENT_SETTLEMENT_CHECKPOINT_20260919.md` — calculated invoice settlement states and customer statements combining authoritative opening controls with approved target-ERP activity.
- `docs/EXPENSE_PETTY_CASH_CHECKPOINT_20260921.md` — receipt-backed expenses, UAE VAT evidence, reimbursements, petty-cash advances and balanced non-posting rehearsals.
- `docs/ERP_FOUNDATION_CHECKPOINT.md` — locked target organization, locations, numbering evidence, source-key registry, approvals and migration batch.
- `docs/CANONICAL_MASTER_CHECKPOINT.md` — source-linked party, product, UOM, tax and opening-balance approval masters.
- `docs/CANONICAL_TRANSACTION_CHECKPOINT.md` — non-posting documents, lines, payments, inventory movements and exception queue.
- `docs/CANONICAL_ACCOUNTING_CHECKPOINT.md` — locked GL, journals, AR/AP, VAT, cash, trial balance and financial activation gates.
- `docs/SECURITY_WORKFLOW_CHECKPOINT.md` — disabled users/RBAC, location scopes, approval bindings, SoD and security gates.
- `docs/PRODUCTION_SECURITY_DEPLOYMENT_CHECKPOINT_20260909.md` — fail-closed production configuration, persistent sessions, TLS/host controls and activation runbook.
- `docs/SOURCE_COVERAGE_CHECKPOINT.md` — every raw row mapped, classified or explicitly blocked for structured promotion.
- `docs/RESIDUAL_WORKFLOW_CHECKPOINT.md` — portal, quotation/draft, shipment, sales-target and transfer-detail structures.
- `docs/APPLICATION_FOUNDATION_CHECKPOINT.md` — read-only API, migration dashboard and HTTP safety controls.
- `docs/RUNTIME_ARCHITECTURE_CHECKPOINT.md` — migrations, disabled authentication, protected detail APIs, approval state machine and runtime activation gates.
- `docs/DEPLOYMENT_MODULE_CHECKPOINT.md` — aggregate module workspaces, container packaging, security posture and verification evidence.
- `docs/POSTGRESQL_VALIDATION_CHECKPOINT.md` — synthetic PostgreSQL migration, RBAC/location, restart, backup/restore and cleanup evidence.
- `docs/SQLITE_POSTGRES_COPY_CHECKPOINT.md` — guarded full clone copy, per-table digests, source immutability and PostgreSQL dashboard reconciliation.
- `docs/DELTA_DRY_RUN_CHECKPOINT.md` — isolated non-posting transformation of the dated UI delta packages.
- `docs/DELTA_MERGE_SIMULATION_CHECKPOINT.md` — duplicate-aware merge plan against a disposable clone copy.
- `docs/STOCK_LOCATION_RECONCILIATION_CHECKPOINT.md` — authoritative SKU `98081` location export and zero-conflict rerun.
- `docs/CUTOVER_READINESS_CHECKPOINT.md` — fail-closed final-capture inventory, hashes and external cutover gates.
- `docs/CUTOVER_CAPTURE_REHEARSAL_CHECKPOINT.md` — verified non-atomic package rehearsal for all preserved evidence.
- `docs/SOURCE_ACTIVITY_WATERMARK_CHECKPOINT.md` — read-only pre-freeze counts and fail-closed activity comparison.
- `docs/INVENTORY_OPERATIONS_FOUNDATION_CHECKPOINT_20260909.md` — controlled transfer/adjustment documents, reservations, approval and posting rehearsal.
- `docs/USERS_ROLES_APPROVAL_MATRIX_CHECKPOINT_20260915.md` — operational user profiles, multi-role scoped assignments, effective permissions and maker/approver controls.
- `docs/FINANCE_APPROVAL_QUEUE_CHECKPOINT_20260915.md` — revision-controlled chart-account and mapping approval workflow with independent decisions.
- `docs/ERP_MASTER_IMPORT_REHEARSAL_CHECKPOINT.md` — incremental master-data package, isolated ERP validation and non-posting staging placement.
- `source_exports/2026-09-08/DETAIL_HASHES.sha256` — hash ledger for browser-only detail evidence.

## Staging commands

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli init-db
python -m klen_clone.cli import --source 'source_exports\2026-09-08' --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli transform --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli resolve --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli inventory --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli financial --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli accounting --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli blueprint --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli foundation --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli masters --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli transactions --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli ledger --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli security --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli coverage --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli residuals --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli coverage --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli runtime --snapshot 'bizmodo-2026-09-08-browser'
python -m klen_clone.cli reconcile --snapshot 'bizmodo-2026-09-08-browser'
```

Validate a dated UI delta in a new disposable SQLite database. The command verifies the evidence manifest, refuses existing or protected database targets, and never promotes records into the preserved clone:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli delta-dry-run `
  --source 'source_exports\2026-09-09-ui-delta' `
  --output 'var\delta_dry_runs\<new-run-id>\delta_validation.db'
```

Simulate the validated delta against a new SQLite backup of the preserved clone. Only merge-plan tables are added to the disposable output; existing business tables are not changed:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli delta-merge-simulate `
  --clone 'var\klen_staging.db' `
  --delta 'var\delta_dry_runs\<dry-run-id>\delta_validation.db' `
  --output 'var\delta_merge_simulations\<new-run-id>\merge_simulation.db'
```

Build a fail-closed cutover-readiness manifest without changing the preserved inputs:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli cutover-readiness `
  --baseline 'source_exports\2026-09-08' `
  --delta 'source_exports\2026-09-09-ui-delta' `
  --clone 'var\klen_staging.db' `
  --delta-database 'var\delta_dry_runs\20260908T224316Z\delta_validation.db' `
  --simulation-database 'var\delta_merge_simulations\20260908T224332Z\merge_simulation.db' `
  --output 'var\cutover_readiness\<new-run-id>\cutover-readiness.json'
```

Rehearse the complete checksum-bound capture package without claiming an atomic source snapshot:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli cutover-rehearsal `
  --baseline 'source_exports\2026-09-08' `
  --delta 'source_exports\2026-09-09-ui-delta' `
  --readiness 'var\cutover_readiness\<readiness-run-id>\cutover-readiness.json' `
  --output 'var\cutover_rehearsals\<new-run-id>\cutover-rehearsal.zip'
```

Compare opening and closing source-activity markers. The command exits non-zero if a reliable stream changes and never enables merge or posting:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli compare-watermarks `
  --before 'source_exports\<cutover-id>\opening-watermark.json' `
  --after 'source_exports\<cutover-id>\closing-watermark.json' `
  --output 'var\activity_watermarks\<run-id>\comparison.json'
```

Prepare source-keyed ERP master templates from a sealed browser capture. The command verifies source hashes, records transformation exceptions, and never posts into ERP business tables:

```powershell
$env:PYTHONPATH='src'
python -m klen_clone.cli erp-master-rehearsal `
  --capture 'source_exports\2026-09-09-current-non-atomic' `
  --output 'var\erp_import_rehearsals\<new-run-id>\package'
```

Prepare a checksum-bound, non-posting opening AR/AP and provisional stock package:

```powershell
python -m klen_clone.cli erp-opening-rehearsal `
  --capture source_exports/2026-09-09-current-non-atomic `
  --baseline source_exports/2026-09-08 `
  --output var/erp_opening_rehearsals/<timestamp>/package
```

The completed 2026-09-09 checkpoint and unresolved reconciliation differences are recorded in `docs/ERP_OPENING_REHEARSAL_CHECKPOINT.md`.

The fresh stock and partner-balance correction checkpoint is recorded in `docs/ERP_RECONCILIATION_REFRESH_20260909.md`.

Set `KLEN_DATABASE_URL` to a PostgreSQL SQLAlchemy URL for shared staging. When it is unset, the service uses the confidential local database `var/klen_staging.db`, which is excluded from source control.

For a new, empty deployment database, apply the versioned schema before running the pipeline:

```powershell
$env:PYTHONPATH='src'
python -m alembic upgrade head
```

The baseline migration is for a new database. An existing populated database must be inspected and stamped through a separately approved procedure; do not point the baseline at it casually.

## Read-only control center

```powershell
$env:PYTHONPATH='src'
python -m uvicorn klen_clone.web:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`. The current application is a local migration-assurance interface, not an operational ERP release. It exposes aggregate controls only, rejects mutating HTTP methods, and does not enable authentication or posting.

The locked module navigation is intentional. Protected detail APIs return `503` until authentication, RBAC, location scope and deployment gates are explicitly completed. There is no password provisioning, login route, approval execution or posting route in this checkpoint.

## Independent Asas ERP preview

The independent preview runs at `http://127.0.0.1:18082/`. It reads the canonical
clone database and mounts `source_exports/2026-09-09-current-non-atomic` read-only
as a provisional delta overlay. Startup verifies every declared checksum and row
count before exposing later register headers. Overlay records are labelled
`provisional_overlay`; incomplete child details cannot be posted. This service
does not depend on or reuse `D:\Klen+ ERP`.

Authenticated sales and purchase draft entry is available at `#drafts`. Drafts
are stored in the separate `asas_erp_operational` PostgreSQL service and are
validated against cloned party, product and location masters. They are expressly
non-posting: no inventory, accounting, tax, payment, or source-system record is
created. See `docs/OPERATIONAL_DRAFT_FOUNDATION_CHECKPOINT_20260909.md`.

Operational schema versions `0001` through `0020` are checksum-recorded.
Drafts use database row locks plus optimistic revision checks, immutable workflow
events, controlled submit/cancel/approve transitions, and per-line base-quantity
snapshots. Product, party and location selectors and printable review are active.
Self-approval is blocked. The separately provisioned approver can run a
transactional posting rehearsal that proves balanced control-account projections
and rolls every probe row back; real posting remains disabled.
Both roles are explicitly scoped to cloned locations `DXB`, `MAIN`, `RAK` and
`SHJ`. Sales rehearsal includes COGS and inventory value from the captured cost
basis; purchase rehearsal allocates header discount across incoming stock value.
The first PostgreSQL backup/restore drill is recorded in
`docs/OPERATIONAL_BACKUP_SCOPE_VALUATION_CHECKPOINT_20260909.md`.

### Production deployment template

`compose.production.yaml` is a hardened overlay for an approved reverse-proxy deployment. It removes workstation evidence mounts and local port publishing, requires external clone and operational PostgreSQL URLs, uses a Docker secret for provisioned identities, enables persistent database sessions, validates explicit hosts and trusted proxy addresses, and keeps posting disabled unless confirmation plus an approval reference are both supplied.

Validate it with environment-specific secret references before deployment:

```powershell
docker compose -f compose.yaml -f compose.production.yaml config --quiet
```

Do not activate posting during the infrastructure deployment. Complete TLS, backup/restore, monitoring, access review and final BizModo reconciliation first.

Migration `0005` adds stock-position and reservation bounds, fiscal-period
rehearsal locks, deterministic posting fingerprints, permanent journal and
subledger schemas, and reversal projections. Migration `0006` adds
checksum-bound opening-stock batches, negative-stock quarantine, governed period
metadata and inventory-ledger entries. The reconciled non-atomic opening package
is staged as 579 positive location/SKU balances with four genuine negative rows
quarantined; its net is 29,124.02 base units. The earlier provisional minus-171
variance was superseded by exact source reconciliation and was not applied.

Atomic posting and exact reversal services are implemented and tested, but both
HTTP operations remain disabled by the global posting flag and dedicated
permissions. See `docs/OPENING_STOCK_ATOMIC_POSTING_CHECKPOINT_20260909.md`.

Migration `0007` stages checksum-bound contact-level opening AR/AP and partner
advances without creating journals or asserting invoice ageing. The live control
set contains 196 receivables, 53 payables, nine customer advances and six
supplier advances. Three header/report variances remain open and visible. See
`docs/OPENING_AR_AP_CHECKPOINT_20260909.md`.

The service now requires independently provisioned Asas users. Password hashes
and role permissions are stored in the ignored `.secrets/asas-users.json` file,
which is mounted read-only into the ERP container. Copied BizModo users remain
disabled. See `docs/ASAS_AUTHENTICATION_CHECKPOINT_20260909.md` for the current
security controls and remaining production gates.

The Sales, Purchasing, Inventory, Accounting, CRM, Delivery and Reports navigation items open aggregate assurance workspaces sourced from the cloned database. These workspaces do not expose names, contact details, document rows or source payloads.

## Independent ERP preview

The standalone Asas ERP preview is implemented entirely in this repository and reads the cloned canonical BizModo tables. It does not import or reuse the separate `D:\Klen+ ERP` application.

When the clone Docker stack is running, open `http://127.0.0.1:18082/`. The preview provides live overview, sales, sales-order, delivery-fulfilment, customer-invoice, customer-credit and collections, bank and cash reconciliation, expense and petty-cash control, fixed-assets, enterprise procurement, purchasing, inventory, products, customers, suppliers, accounting, HRM, financial statements, audit and compliance, and reports workspaces. HRM is included and payroll is excluded. The sales-order workspace governs customer quotation revision, independent approval, customer acceptance and immutable conversion to a confirmed order. Delivery fulfilment then controls stock allocation, picking, dispatch/delivery-note stock issue and proof of delivery; only a delivered order with POD is invoice-eligible. Customer invoicing copies that delivered order snapshot, prevents duplicate/excess invoicing, applies independent approval, and rehearses receivables/revenue/VAT without issuing stock a second time or permanently posting accounting. Credit control adds maker-checker limits and terms, exposure plus open-order commitments, customer holds, target-ERP overdue monitoring, collection actions, promise-to-pay tracking, independently approved one-time blocked-order overrides, and sequential dunning escalation; configured holds and limit breaches block ordinary order conversion. Bank and cash management adds independently approved account masters, duplicate-protected balanced statement import, approved receipt/payment matching, documented exceptions, reconciliation approval, and fingerprinted non-posting adjustment rehearsal. Expense control adds receipt-backed claims, UAE VAT evidence, reimbursements, approved-account settlement and petty-cash advance lifecycle controls. Fixed-assets control adds maker-checker capitalization, straight-line depreciation schedules, controlled disposal approval, and fingerprinted non-posting accounting rehearsals. Close-to-report freezes approved financial statements with controlled PDF and Excel exports. Audit and compliance then hash-chains the consolidated operational audit trail, checks approved VAT/report fingerprints and posting/filing locks, and releases statutory evidence workbooks and manifests only after independent approval. The procurement workspace governs purchase requisition, RFQ, supplier quotation comparison, award and purchase-order approval. The service binds only to loopback; authenticated operational changes remain isolated from BizModo, while accounting posting, statutory filing and production activation stay disabled until their cutover controls are completed. See `docs/SALES_QUOTATION_ORDER_CHECKPOINT_20260919.md`, `docs/DELIVERY_FULFILLMENT_CHECKPOINT_20260919.md`, `docs/CUSTOMER_INVOICE_CHECKPOINT_20260919.md`, `docs/CUSTOMER_CREDIT_COLLECTIONS_CHECKPOINT_20260919.md`, `docs/CREDIT_OVERRIDE_DUNNING_CHECKPOINT_20260919.md`, `docs/BANK_CASH_RECONCILIATION_CHECKPOINT_20260919.md`, `docs/EXPENSE_PETTY_CASH_CHECKPOINT_20260921.md`, `docs/FIXED_ASSETS_CHECKPOINT_20260921.md`, `docs/CLOSE_TO_REPORT_CHECKPOINT_20260921.md`, and `docs/AUDIT_COMPLIANCE_CHECKPOINT_20260921.md`.

The UAE VAT control centre adds source-backed output/input tax reconciliation, independently approved reverse-charge and correction adjustments, frozen period evidence, and balanced non-filing return rehearsals. The month-end close centre adds governed close checklists, approved accrual/prepayment/FX/inventory adjustments, frozen period snapshots and balanced lock rehearsals. Close-to-report adds fingerprinted trial balance, profit and loss, balance sheet, cash flow, retained earnings, comparisons, drill-down references, and approval-gated PDF/Excel exports. See `docs/UAE_VAT_CONTROL_CHECKPOINT_20260921.md`, `docs/MONTH_END_CLOSE_CHECKPOINT_20260921.md`, and `docs/CLOSE_TO_REPORT_CHECKPOINT_20260921.md`.

## Controlled cutover reset rehearsal

The authenticated **Cutover rehearsal** workspace snapshots all target operational table counts, calculates a foreign-key-safe child-first purge order, records final-source and rollback blockers, and produces approval-controlled Excel and JSON plans. It has no purge or import execution endpoint. Approval confirms the rehearsal plan only; all test data remains untouched until a later separately authorized final cutover. See `docs/CUTOVER_RESET_REHEARSAL_CHECKPOINT_20260921.md`.

## Isolated container preview

The compose profile creates a new PostgreSQL volume and binds the control center to loopback only. It does not mount `source_exports`, `var` or any source-system session material.

```powershell
$env:KLEN_POSTGRES_PASSWORD='provide-a-long-url-safe-secret'
docker compose config --quiet
docker compose up --build
```

This is deployment packaging for a non-operational assurance environment. It starts with an empty schema; cloned data must be loaded through a separately controlled import and reconciliation process. Do not enable production mode or authentication until the runtime activation gates are approved.

The guarded copy command requires an empty PostgreSQL target and an explicit SQLite source URL. It opens SQLite in query-only mode, preserves IDs, reseeds PostgreSQL sequences, and rolls back unless every application table matches by row count and deterministic SHA-256 digest:

```powershell
$env:KLEN_DATABASE_URL='postgresql+psycopg://...'
$env:PYTHONPATH='src'
python -m klen_clone.cli copy-db --source-url 'sqlite:///var/klen_staging.db'
```

Stage a checksum-verified frozen browser delta in a new disposable database:

```powershell
python -m klen_clone.cli browser-delta-stage --capture source_exports/2026-09-10-frozen-browser-cutover --output var/frozen_browser_delta_staging/run/browser_delta_staging.db
```

This command refuses existing outputs and capture-integrity failures. Its
database is explicitly marked validation-only with production merge and posting
disabled.
