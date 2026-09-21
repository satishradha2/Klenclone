# Independent Asas ERP preview checkpoint

Date: 2026-09-09

## Outcome

An independent, read-only ERP preview now runs entirely from `D:\Klen Clone`.
It does not import, mount, call, or reuse the separate `D:\Klen+ ERP` project.

- Application identity: Asas ERP
- Local URL: `http://127.0.0.1:18082/`
- API mode: `independent_clone_preview`
- Source database: the BizModo browser-capture clone database in this workspace
- Posting: disabled
- HRM: included; payroll: excluded
- Live BizModo writes: none
- Authentication: required; independent `preview_administrator` provisioned

## Available modules

- Overview
- Sales and sales returns
- Purchasing and purchase returns
- Inventory
- Products
- Customers
- Suppliers
- Accounting controls
- Migration reports

## Baseline and provisional delta represented

The preview retains the canonical, non-atomic browser snapshot identified as
`bizmodo-2026-09-08-browser` and now overlays the sealed later visible-register
capture from `source_exports/2026-09-09-current-non-atomic`. Every mounted file
hash and declared row count is verified at startup; any mismatch fails closed.

| Area | Current canonical count |
| --- | ---: |
| Customers | 794 |
| Suppliers | 88 |
| Products | 465 |
| Sales | 3,584 |
| Purchases | 447 |
| Sales returns | 38 |
| Purchase returns | 9 |
| Stock transfers | 920 |
| Inventory movements | 18,022 |
| Inventory product/location groups | 1,211 |
| Captured exceptions | 188 |

The original canonical counts remain preserved in the database. Missing later
register rows are presented as `provisional_overlay` records, not silently
promoted or posted. Relative to the prior watermark, the latest sealed package
adds two sale headers and three stock-transfer headers; their full child-detail
capture is incomplete. These figures are therefore not a claim of final
reconciliation or production readiness.

## Isolation controls

- Docker service: `erp-preview`
- Dedicated loopback port: `18082`
- Filesystem: read-only inside the application container
- HTTP mutation methods: rejected
- Database use: read-only application behavior
- Delta evidence mount: read-only with startup hash and row-count validation
- Branding and identity: Asas ERP, with no KLEN+ or OrbisHub dependency

## Verification

- Full automated suite: 84 passed, 1 skipped
- Python compilation: passed
- Health endpoint: application and database healthy
- Browser smoke test: reports and sales rendered; newest sale `AK2026-03623`
  appears with `provisional_overlay` status
- Browser console: no warnings or errors during the smoke test
- Authentication, CSRF, throttling and append-only login audit tests: passed

## Remaining work before operational use

1. Capture and reconcile missing child details for the newest sale and transfer
   headers, then promote the complete delta into a new canonical snapshot.
2. Resolve or explicitly accept inventory, receivable and payable exceptions.
3. Implement authentication, roles, audit logging and controlled write workflows.
4. Implement operational sales, purchasing, stock and accounting posting against
   a dedicated Asas ERP production database.
5. Run an authenticated end-to-end smoke test and a final delta capture.
6. Obtain a transaction-free cutover window for the final best-available copy.

Until those steps are complete, this instance is a safe data-review preview and
must not be used as the live transaction system.
