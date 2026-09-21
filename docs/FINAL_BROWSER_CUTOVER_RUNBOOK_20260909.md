# Final browser cutover runbook

Status: **prepared; source still active; execution not authorized before freeze**

This runbook is for the best-achievable BizModo V7.5.1 migration using the authenticated browser account. It never creates, edits, approves, cancels, deletes or posts anything in BizModo. HRM is included in the new ERP; payroll is excluded.

## Preconditions

1. The business confirms all BizModo users have stopped sales, purchases, payments, returns, transfers, stock adjustments and master-data changes.
2. The freeze begins after 00:00 Asia/Dubai on the agreed cutover date.
3. The authenticated BizModo session is still valid.
4. The local ERP and operational PostgreSQL services are healthy.
5. Production posting remains disabled and no provisional data is promoted during capture.

If any source activity is observed after the opening watermark, invalidate the run and restart from a new opening watermark.

## Opening watermark

Record count, active date scope, latest immutable reference and latest timestamp where available for:

- products, customers and suppliers;
- sales, POS, drafts, quotations, shipments, sales returns and sales payments;
- purchases, purchase orders, purchase returns and purchase payments;
- stock by location, stock transfers, stock adjustments and traceability registers;
- payment accounts, cash flow, VAT, trial balance and profitability;
- users, roles, permissions, settings and CRM configuration;
- Complete HRM migration evidence for controlled operational import, without payroll data.

## Controlled exports

Export every accessible register using explicit full-period or all-record scopes. Preserve the original downloaded files unchanged. For each file record:

- source URL and visible filter scope;
- capture start and completion time;
- displayed row count and exported data-row count;
- first and last source references;
- SHA-256 checksum;
- any missing columns, access restrictions or inconsistent totals.

Capture detail lines separately wherever a header export does not include quantities, UOM snapshots, taxes, allocations, batches, serials or linked documents.

## Reconciliation

Before any import or promotion:

1. Match exported row counts to displayed register counts for the same scope.
2. Reconcile sales, receipts, returns and customer balances.
3. Reconcile purchases, payments, returns and supplier balances.
4. Reconcile stock quantity by SKU and location, including transfer and adjustment effects.
5. Reconcile VAT, trial balance and control-account totals.
6. Reject duplicate source IDs and unresolved foreign keys.
7. Preserve source IDs and UOM conversion snapshots so cloned history follows the new ERP rules after promotion.

The known provisional stock correction of minus 171 units across 26 SKUs and unresolved AR/AP header differences remain explicit exceptions until evidence-backed adjustments are approved. They must not be silently forced into balance.

## Closing watermark and gate

Repeat the opening watermark after all exports finish. The run passes only when every reliable count and latest key is unchanged. A passing comparison permits a staging import and reconciliation rehearsal; it does not by itself enable production posting.

Production activation additionally requires a recoverable production backup, approved security configuration, authenticated smoke tests, balanced posting/reversal checks and explicit cutover approval.

## Credential-only limitation

This procedure can capture browser-accessible records but cannot prove atomic database completeness, hidden/deleted rows or uploaded-file completeness. A hosting-provider database and uploaded-file backup remains the stronger and preferred final migration source.
