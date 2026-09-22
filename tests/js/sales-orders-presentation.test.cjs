const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');

const root = join(__dirname, '../..');
const shell = readFileSync(join(root, 'src/klen_clone/static/erp.html'), 'utf8');
const source = readFileSync(join(root, 'src/klen_clone/static/sales-orders.js'), 'utf8');
const deliveries = readFileSync(join(root, 'src/klen_clone/static/deliveries.js'), 'utf8');
const customerInvoices = readFileSync(join(root, 'src/klen_clone/static/customer-invoices.js'), 'utf8');
const crm = readFileSync(join(root, 'src/klen_clone/static/crm.js'), 'utf8');
const payments = readFileSync(join(root, 'src/klen_clone/static/payments.js'), 'utf8');
const cashManagement = readFileSync(join(root, 'src/klen_clone/static/cash-management.js'), 'utf8');
const expenses = readFileSync(join(root, 'src/klen_clone/static/expenses.js'), 'utf8');
const fixedAssets = readFileSync(join(root, 'src/klen_clone/static/fixed-assets.js'), 'utf8');
const vatControl = readFileSync(join(root, 'src/klen_clone/static/vat-control.js'), 'utf8');
const periodClose = readFileSync(join(root, 'src/klen_clone/static/period-close.js'), 'utf8');
const closeReporting = readFileSync(join(root, 'src/klen_clone/static/close-reporting.js'), 'utf8');
const financialReports = readFileSync(join(root, 'src/klen_clone/static/financial-reports.js'), 'utf8');
const styles = readFileSync(join(root, 'src/klen_clone/static/workspace-components.css'), 'utf8');
const components = readFileSync(join(root, 'src/klen_clone/static/workspace-components.js'), 'utf8');
const erp = readFileSync(join(root, 'src/klen_clone/static/erp.js'), 'utf8');
const inspector = readFileSync(join(root, 'src/klen_clone/static/workspace-inspector.js'), 'utf8');
const inspectorStyles = readFileSync(join(root, 'src/klen_clone/static/workspace-inspector.css'), 'utf8');

test('shared component layer loads after the shell foundation', () => {
  const foundation = shell.indexOf('/static/workspace-shell.css');
  const components = shell.indexOf('/static/workspace-components.css');
  assert.ok(foundation >= 0);
  assert.ok(components > foundation);
});

test('central workspace API loads before page modules and owns reusable presentation behavior', () => {
  const framework = shell.indexOf('/static/workspace-components.js');
  const firstPageModule = shell.indexOf('/static/purchase-returns.js');
  assert.ok(framework >= 0);
  assert.ok(framework < firstPageModule);
  for (const contract of ['workflow', 'panel', 'form', 'caption', 'feedback', 'controlNote', 'taskWorkspace', 'migrate', 'observe']) {
    assert.match(components, new RegExp(`const ${contract} =|${contract},`));
  }
  assert.match(components, /window\.WorkspaceUI = Object\.freeze/);
  assert.doesNotMatch(components, /fetch\(|XMLHttpRequest|\/api\/v1/);
});

test('central task workspace progressively discloses dense routes without business API calls', () => {
  assert.match(components, /const taskWorkspace = \(root, options = \{\}\)/);
  assert.match(components, /workspace-taskbar/);
  assert.match(components, /workspace-task-tab/);
  assert.match(components, /workspace-task-pane/);
  assert.match(components, /workspace-action-drawer/);
  assert.match(components, /role', 'tablist/);
  assert.match(components, /ArrowLeft.*ArrowRight.*Home.*End/);
  assert.match(components, /sessionStorage\.setItem\(storageKey, item\.key\)/);
  assert.match(components, /history\.replaceState/);
  assert.doesNotMatch(components, /fetch\(|XMLHttpRequest|\/api\/v1/);
  assert.match(styles, /\.workspace-taskbar\{/);
  assert.match(styles, /backdrop-filter:blur\(18px\) saturate\(1\.14\)/);
  assert.match(styles, /@keyframes task-pane-enter/);
  assert.match(styles, /@keyframes task-drawer-enter/);
  assert.match(styles, /data-motion=reduced/);
  assert.match(shell, /workspace-components\.css\?v=20260922-pricing-control-4/);
  assert.match(shell, /workspace-components\.js\?v=20260922-task-workspace-3/);
});

test('every routed workspace is centrally migrated on initial render and later rerenders', () => {
  assert.match(erp, /WorkspaceUI\.observe\(content/);
  assert.match(erp, /finally\{WorkspaceUI\.migrate\(content,\{route:active,title:routes\[active\]\}\)\}/);
  assert.match(erp, /else if\(active==='crm'\)await crmWorkspace\(\)/);
  assert.match(components, /root\.querySelectorAll\('\.panel'\)\.forEach\(element => panel\(element\)\)/);
  assert.match(components, /root\.querySelectorAll\('\.table-wrap'\)/);
  assert.match(components, /root\.querySelectorAll\('\.filters'\)/);
  assert.match(styles, /\.central-workspace/);
  assert.match(styles, /\.central-table-region/);
  assert.match(styles, /\.central-filter-form/);
  assert.doesNotMatch(crm, /stopImmediatePropagation|addEventListener\('hashchange'/);
});

test('record inspector and attention center are centralized and read-only', () => {
  assert.match(shell, /id="attention-trigger"/);
  assert.match(shell, /id="attention-center"/);
  assert.match(shell, /id="record-inspector"/);
  assert.match(shell, /\/static\/workspace-inspector\.js\?v=/);
  assert.match(components, /inspectable-row/);
  assert.match(inspector, /fetch\('\/api\/v1\/my-workspace'/);
  assert.match(inspector, /tr\.inspectable-row/);
  assert.match(shell, /Only data already visible|READ-ONLY RECORD VIEW/);
  assert.doesNotMatch(inspector, /method:\s*['"](?:POST|PUT|PATCH|DELETE)/i);
  assert.doesNotMatch(inspector, /X-CSRF-Token/);
  assert.match(inspectorStyles, /\.workspace-drawer/);
  assert.match(inspectorStyles, /@media\(max-width:620px\)/);
});

test('sales-order pilot applies semantic presentation without replacing workflow endpoints', () => {
  assert.match(source, /enhanceSalesOrderPresentation\(\)/);
  assert.match(source, /const ui=WorkspaceUI/);
  assert.match(source, /aria-label="Product SKU"/);
  assert.match(source, /ui\.feedback|feedback:\[/);
  assert.match(components, /setAttribute\('role', 'status'\)/);
  assert.match(source, /Customer quotation approval register/);
  assert.match(source, /\/api\/v1\/sales-orders\/quotations/);
  assert.match(source, /expected_revision/);
  assert.match(source, /\/api\/v1\/commercial-pricing\/price-lists/);
  assert.match(source, /formElement\.promotion_code\.value=q\.promotion_code\|\|''/);
  assert.match(source, /const applyPricingAssist=/);
  assert.match(source, /Approved prices are locked/);
  assert.match(source, /price\.readOnly=Boolean\(item\)/);
});

test('component layer includes responsive forms, line editors and feedback states', () => {
  for (const selector of ['.component-form', '.form-grid', '.line-editor', '.action-bar', '.feedback', '.record-panel']) {
    assert.ok(styles.includes(selector), `missing ${selector}`);
  }
  assert.match(styles, /@media\(max-width:620px\)/);
});

test('legacy workspaces are normalized into the responsive enterprise form system', () => {
  assert.match(components, /:scope > \.draft-fields:not\(\.form-grid\)/);
  assert.match(components, /\['form-grid', 'central-form-grid'\]/);
  assert.match(components, /legacy-workspace-form/);
  assert.match(components, /legacy-form-actions/);
  assert.match(styles, /\.legacy-workspace-form/);
  assert.match(styles, /repeat\(auto-fit,minmax\(min\(100%,180px\),1fr\)\)/);
});

test('central table regions align both header corners without a reserved scrollbar gutter', () => {
  assert.match(styles, /\.central-table-region\{[^}]*overflow-x:auto[^}]*overflow-y:hidden[^}]*scrollbar-gutter:auto/);
  assert.doesNotMatch(styles, /scrollbar-gutter:stable/);
  assert.match(shell, /workspace-components\.css\?v=20260922-pricing-control-4/);
});

test('shared workspace surfaces use restrained blur while preserving contrast mode', () => {
  assert.match(styles, /\.component-form,.legacy-workspace-form,.central-toolbar,.workflow-steps,.control-note,.close-package-actions/);
  assert.match(styles, /backdrop-filter:blur\(10px\) saturate\(1\.06\)/);
  assert.match(styles, /data-theme=contrast.*backdrop-filter:none!important/);
  assert.match(shell, /workspace-components\.css\?v=20260922-pricing-control-4/);
  assert.match(inspectorStyles, /\.workspace-drawer\{background:var\(--glass-elevated\)/);
  assert.match(inspectorStyles, /workspace-drawer::backdrop.*backdrop-filter:blur\(8px\)/);
});

test('record inspector keeps its body and actions in fixed drawer rows with readable cell separation', () => {
  assert.match(inspectorStyles, /\.record-inspector>form\{grid-template-rows:auto minmax\(0,1fr\) auto auto\}/);
  assert.match(inspectorStyles, /\.attention-center>form\{grid-template-rows:auto auto minmax\(0,1fr\) auto\}/);
  assert.match(inspector, /const renderedText = node/);
  assert.match(inspector, /\.map\(renderedText\)/);
  assert.match(components, /const readableText = element/);
});

test('delivery pilot reuses the component layer without changing workflow endpoints', () => {
  assert.match(deliveries, /enhanceDeliveriesPresentation\(\)/);
  assert.match(deliveries, /ui\.workflow\(/);
  assert.match(deliveries, /Confirmed orders ready for stock allocation/);
  assert.match(deliveries, /\/api\/v1\/deliveries\/orders\/\$\{encodeURIComponent\(button\.dataset\.key\)\}\/allocate/);
  assert.match(deliveries, /\/proof-of-delivery/);
  assert.match(deliveries, /expected_revision/);
  assert.match(styles, /\.workflow-steps/);
});

test('customer invoices reuse the workflow and financial presentation contracts', () => {
  assert.match(customerInvoices, /enhanceCustomerInvoicesPresentation\(\)/);
  assert.match(customerInvoices, /className:'invoice-flow'/);
  assert.match(customerInvoices, /Customer invoice approval and settlement register/);
  assert.match(customerInvoices, /workflow-dialog-form/);
  assert.match(customerInvoices, /\/api\/v1\/customer-invoices\/deliveries/);
  assert.match(customerInvoices, /\/posting-rehearsal/);
  assert.match(customerInvoices, /expected_revision/);
  assert.match(styles, /\.invoice-board \.financial-cell/);
  assert.match(styles, /\.control-note/);
});

test('sales returns reuse the controlled workflow and disposition presentation contracts', () => {
  const erp = readFileSync(join(root, 'src/klen_clone/static/erp.js'), 'utf8');
  assert.match(erp, /enhanceSalesReturnsPresentation\(\)/);
  assert.match(erp, /className:'return-flow'/);
  assert.match(erp, /Sales return approval and credit-note register/);
  assert.match(erp, /Returned items and controlled stock disposition/);
  assert.match(erp, /\/api\/v1\/sales-returns\/\$\{b\.dataset\.key\}\/\$\{b\.dataset\.action\}/);
  assert.match(erp, /expected_revision/);
  assert.match(styles, /\.return-capture \.return-notes/);
  assert.match(styles, /\.return-board \.financial-cell/);
});

test('payments reuse the allocation workflow and financial presentation contracts', () => {
  assert.match(payments, /enhancePaymentsPresentation\(\)/);
  assert.match(payments, /className:'payment-flow'/);
  assert.match(payments, /Open-item allocations and retained advance balance/);
  assert.match(payments, /Receipt and supplier-payment approval register/);
  assert.match(payments, /aria-label="Allocation amount AED"/);
  assert.match(payments, /\/api\/v1\/payments\/\$\{b\.dataset\.key\}\/\$\{b\.dataset\.action\}/);
  assert.match(payments, /expected_revision/);
  assert.match(styles, /\.payment-capture \.payment-notes/);
  assert.match(styles, /\.payment-board \.financial-cell/);
});

test('bank and cash reuses the reconciliation workflow and control presentation contracts', () => {
  assert.match(cashManagement, /enhanceCashManagementPresentation\(\)/);
  assert.match(cashManagement, /className:'cash-flow'/);
  assert.match(cashManagement, /Approved bank and cash account master register/);
  assert.match(cashManagement, /Statement line matching and exception register/);
  assert.match(cashManagement, /Every bank-statement line must be matched or explained/);
  assert.match(cashManagement, /\/api\/v1\/cash-management\/statements\/\$\{button\.dataset\.key\}\/actions\/\$\{button\.dataset\.action\}/);
  assert.match(cashManagement, /expected_revision/);
  assert.match(styles, /\.cash-control-form/);
  assert.match(styles, /\.reconciliation-board/);
});

test('expenses reuse the evidence, approval and settlement presentation contracts', () => {
  assert.match(expenses, /enhanceExpensesPresentation\(\)/);
  assert.match(expenses, /className:'expense-flow'/);
  assert.match(expenses, /Receipt-backed expense approval register/);
  assert.match(expenses, /Petty-cash issue and settlement register/);
  assert.match(expenses, /rehearsals validate the expense, VAT, payable, cash and advance balances/);
  assert.match(expenses, /\/api\/v1\/expense-management\/claims\/\$\{button\.dataset\.key\}\/actions\/\$\{button\.dataset\.action\}/);
  assert.match(expenses, /expected_revision/);
  assert.match(styles, /\.expense-control-form/);
  assert.match(styles, /\.expense-board \.financial-cell/);
});

test('fixed assets reuse the lifecycle and financial presentation contracts', () => {
  assert.match(fixedAssets, /enhanceFixedAssetsPresentation\(\)/);
  assert.match(fixedAssets, /className:'asset-flow'/);
  assert.match(fixedAssets, /Capitalization, depreciation and disposal register/);
  assert.match(fixedAssets, /Straight-line depreciation schedule preview/);
  assert.match(fixedAssets, /rehearsals validate balanced asset accounting/);
  assert.match(fixedAssets, /\/api\/v1\/fixed-assets\/\$\{button\.dataset\.key\}\/actions\/\$\{button\.dataset\.action\}/);
  assert.match(fixedAssets, /expected_revision/);
  assert.match(styles, /\.asset-control-form/);
  assert.match(styles, /\.asset-board \.financial-cell/);
});

test('UAE VAT reuses the evidence reconciliation and approval presentation contracts', () => {
  assert.match(vatControl, /enhanceVatControlPresentation\(\)/);
  assert.match(vatControl, /className:'vat-flow'/);
  assert.match(vatControl, /Effective VAT periods and maker-checker return status/);
  assert.match(vatControl, /Controlled VAT adjustment approval register/);
  assert.match(vatControl, /evidence-backed, independently approved and rehearsed without filing/);
  assert.match(vatControl, /\/api\/v1\/vat-control\/periods\/\$\{b\.dataset\.key\}\/actions\/\$\{b\.dataset\.action\}/);
  assert.match(vatControl, /expected_revision/);
  assert.match(styles, /\.vat-control-form/);
  assert.match(styles, /\.vat-board \.financial-cell/);
});

test('month-end close uses the central checklist, adjustment and rehearsal presentation contracts', () => {
  assert.match(periodClose, /enhancePeriodClosePresentation\(\)/);
  assert.match(periodClose, /const ui=WorkspaceUI/);
  assert.match(periodClose, /className:'close-flow'/);
  assert.match(periodClose, /Evidence-backed month-end adjustment approval register/);
  assert.match(periodClose, /fiscal period remains open and no permanent journal or period lock is created/);
  assert.match(periodClose, /\/api\/v1\/period-close\/\$\{b\.dataset\.key\}\/actions\/\$\{b\.dataset\.action\}/);
  assert.match(periodClose, /expected_revision/);
  assert.match(styles, /\.close-package-grid/);
  assert.match(styles, /\.close-adjustment-board \.financial-cell/);
});

test('financial statements use the central approval, evidence and export presentation contracts', () => {
  assert.match(closeReporting, /enhanceCloseReportingPresentation\(\)/);
  assert.match(closeReporting, /const ui=WorkspaceUI/);
  assert.match(closeReporting, /className:'report-flow'/);
  assert.match(closeReporting, /Approved close revisions eligible for financial reporting/);
  assert.match(closeReporting, /Trial balance with source-backed account evidence/);
  assert.match(closeReporting, /\/api\/v1\/close-reporting\/packages\/\$\{b\.dataset\.key\}\/\$\{b\.dataset\.action\}/);
  assert.match(closeReporting, /expected_revision/);
  assert.match(styles, /\.report-approval-bar/);
  assert.match(styles, /\.report-package-board \.financial-cell/);
});

test('AR and AP ageing uses central filtering, reconciliation and exposure contracts', () => {
  assert.match(financialReports, /enhanceAgeingPresentation\(\)/);
  assert.match(financialReports, /const ui=WorkspaceUI/);
  assert.match(financialReports, /className:'ageing-flow'/);
  assert.match(financialReports, /Party-level control reconciliation and invoice-date ageing/);
  assert.match(financialReports, /control-balance-cell/);
  assert.match(financialReports, /variance-cell/);
  assert.match(financialReports, /\/reports\/ageing\?ledger_kind=/);
  assert.match(styles, /\.ageing-filter-form/);
  assert.match(styles, /\.ageing-board \.variance-cell/);
});

test('customer statements use central selection, reconciliation and balance contracts', () => {
  assert.match(financialReports, /enhanceCustomerStatementsPresentation\(\)/);
  assert.match(financialReports, /className:'statement-flow'/);
  assert.match(financialReports, /Authoritative opening control and approved target-ERP activity/);
  assert.match(financialReports, /statement-balance-cell/);
  assert.match(financialReports, /\/reports\/customer-statement\?party_code=/);
  assert.match(styles, /\.statement-filter-form/);
  assert.match(styles, /\.statement-board \.statement-balance-cell/);
});
