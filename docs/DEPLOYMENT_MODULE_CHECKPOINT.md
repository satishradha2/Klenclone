# Deployment and Module Workspace Checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Checkpoint date: 2026-09-09  
Source-system rule: live BizModo remains read-only.

## Outcome

The local control center now provides seven interactive, aggregate-only ERP assurance workspaces: Sales, Purchasing, Inventory, Accounting, CRM, Delivery and Reports. The same build has a hardened, loopback-only container preview definition for a new isolated PostgreSQL database.

This is not an operational ERP release. Authentication, approval execution, posting, number reservation, source write-back and user provisioning remain disabled.

## Workspace contract

Every module response contains six aggregate KPIs, three reconciled breakdowns and a filtered blocker summary where matching exception evidence exists. Responses explicitly declare:

- `mode = aggregate_read_only`
- `operational_enabled = false`
- `posting_enabled = false`
- `confidential_rows_exposed = false`

Unknown modules, including `hrm`, return HTTP `404`. HRM and payroll evidence remains preserved in the migration dataset but has no target operational workspace.

## Verified cloned-data examples

- Sales: 3,567 sales documents, 38 returns and 8,466 sales lines.
- Purchasing: purchase and supplier evidence available through aggregate controls.
- Inventory: products, UOM profiles, receipts, issues and transfer movements summarized without row disclosure.
- Accounting: 8,325 non-posting journal blueprints; debit and credit blueprints both total 2,457,167.73.
- CRM: party, portal-identity and sales-target evidence summarized with zero active portal logins.
- Delivery: shipment, transfer document and transfer movement relationships summarized.
- Reports: source coverage, exceptions and append-only audit evidence summarized.

Amounts are displayed as recorded values without assigning a currency symbol until the target currency configuration receives business approval.

## Container posture

- Python 3.12 slim runtime using a non-root service account.
- PostgreSQL 17 service with a persistent named volume and no published database port.
- Separate one-shot Alembic migration service.
- Control center bound to `127.0.0.1` only.
- Read-only application filesystem with a restricted temporary filesystem.
- Linux capabilities dropped and privilege escalation disabled.
- Source exports, evidence, local databases, environment secrets, tests and documentation excluded from the image context.
- Container health check calls the read-only health endpoint.

The compose schema passed `docker compose config --quiet`. The control-center image then built successfully on Docker Desktop 4.68.0 / Linux Engine 29.3.1. Image inspection confirmed the non-root `klen` user and configured health check, and a disposable container successfully imported the packaged application.

The first disposable import test identified that the SQLite fallback directory was not writable by the non-root user. The Dockerfile now creates `/app/var` with the correct ownership, the image was rebuilt, and the same test passed. No PostgreSQL service, persistent volume or business-data container was started during this verification.

## Verification

- Python compilation: passed.
- Automated tests: 47 passed.
- Seven module APIs: HTTP `200`, six cards and three breakdown groups each.
- All module APIs: operational false, posting false and confidential-row exposure false.
- Browser verification: Sales and Accounting navigation and contents rendered correctly.
- Browser warning/error log: empty.
- Source-system writes: none.

## Next controlled stage

The synthetic PostgreSQL integration stage is complete; see `POSTGRESQL_VALIDATION_CHECKPOINT.md`. Next, design authenticated read-only detail screens against synthetic fixtures and prepare the controlled SQLite-to-PostgreSQL copy/reconciliation procedure. Real principals, live business-detail access, workflows and posting must remain unavailable until security approval, production secrets, TLS, frozen cutover reconciliation and business UAT are complete.
