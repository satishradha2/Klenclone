# Source system inventory

Source: authenticated read-only inspection of `https://mart.bizmodo.io/`

Application: BizModo V7.5.1  
Business: Asas General Trading LLC  
Inventory date: 2026-09-08  
Currency observed: AED  
Visible business locations: 4

## Source protection

Only navigation, filtering, viewing, printing, and downloading are permitted. Destructive and mutating controls are out of scope even when the authenticated account exposes them.

## Organization and access

| Area | Visible records | Export status | Notes |
|---|---:|---|---|
| Users | 16 | CSV captured | Username, name, role, email |
| Roles | 7 | Six permission matrices captured | Admin is protected and exposes no edit matrix; assigned users are recorded |
| Sales commission agents | 0 | Empty | Module enabled |
| Business locations | 4 | UI inventory only | Location and invoice-layout configuration |

## Parties and CRM

| Area | Visible records | Export status | Notes |
|---|---:|---|---|
| Customers | 793 | CSV captured | Includes balances, grouping, assignment, location and custom fields |
| Suppliers | 88 | CSV captured | Includes balances, tax, address and custom fields |
| Industries | 7 | CSV captured | Reference data |
| Customer groups | 0 | Empty | Module enabled |
| CRM contact logins | 33 | CSV captured with limitation | Username values are blank in the export |
| Leads | 0 for 2026 view | Empty | Date-filtered module enabled |
| Follow-ups | 0 for 2026 view | Empty | Standard and recursive follow-ups enabled |
| Campaigns | 0 | Empty | Module enabled |
| Proposals/templates | 0 | Empty | Module enabled |
| CRM commissions | 0 for 2026 view | Empty | Module enabled |

CRM also exposes reports, proposal layout, settings, life stages, sources, contact login, and lead-conversion views.

## Products and reference data

| Area | Visible records | Export status | Notes |
|---|---:|---|---|
| Products | 464 | CSV captured with limitation | Export contains one trailing UI-contaminated row |
| Units | 202 | CSV captured | 30 repeated name groups require UOM review |
| Categories | 8 | CSV captured | Category hierarchy/code fields exposed |
| Brands | 19 | CSV captured | Reference data |
| Variations | 0 | Empty | Module enabled |
| Selling price groups | 0 | Empty | Import/export capability enabled |
| Warranties | 0 | Empty | Module enabled |
| Product types | 0 | Empty | Module enabled |
| Product-supplier mapping | 0 visible | No usable rows | Relationship module enabled |
| Tax rates | 1 | UI inventory only | One tax rate and no tax groups visible |

## Purchasing

| Area | 2026 records | Export status | Notes |
|---|---:|---|---|
| Purchase requisitions | 0 | Empty | Workflow enabled |
| Purchase orders | 0 | Empty | Workflow enabled |
| Purchases | 446 | CSV captured | Includes status, payment status, totals and due amount |
| Purchase returns | 9 | CSV plus 9 detail forms captured | 41 visible product rows; five parent-linked and four standalone returns |
| Purchase product lines | 1,063 | CSV captured | 445 distinct purchase references; matches the distinct header reference set |
| Purchase payments | 413 | CSV captured | Payment total AED 498,516.40 |

## Sales

| Area | 2026 records | Export status | Notes |
|---|---:|---|---|
| All sales | 3,567 | CSV captured | 3,566 distinct invoice numbers |
| POS sales | 3,394 | CSV captured | All POS invoice keys exist in all-sales export |
| Non-POS sales | 172 distinct invoices | Derived reconciliation | Difference between all sales and POS |
| Drafts | 7 | CSV captured with limitation | Identical to quotation export |
| Quotations | 7 | CSV captured with limitation | Identical to draft export |
| Sales orders | 0 | Empty | Workflow enabled |
| Customer orders | 0 | Empty | Workflow enabled |
| Sales returns | 38 | CSV plus 38 detail views captured | 44 returned-product lines and activity records |
| Shipments | 4 | CSV captured | Shipping and payment states exposed |
| Sales product lines | 8,466 | CSV captured and reconciled | Monthly plus boundary partitions; zero variance to annual UI control |
| Sales payments | 3,653 | CSV captured | Captured later than the header snapshot; snapshot drift is documented |
| Discounts | 0 | Empty | Module enabled |
| Order requests | 0 | Empty | CRM order-request workflow enabled |

## Inventory

| Area | 2026 records | Export status | Notes |
|---|---:|---|---|
| Stock transfers | 916 CSV / 917 later details | CSV plus all detail views captured | 4,219 product lines; one new transfer proves live-source drift |
| Stock adjustments | 0 | Empty | Workflow enabled |
| Stock counts | 0 | Empty | Count and embedded adjustment tables enabled |
| Current stock by location | 1,202 | CSV captured | 465 SKUs; four negative-stock rows; three rows without a location |
| Item traceability | 5,560 | CSV captured | Purchase-to-sale allocation fields, supplier, customer, prices and quantities |
| Product transfer-history report | Enabled | Partial | Report is product/location scoped; global transfer line extraction still required |

## Finance and reporting

| Area | Visible state | Export status | Notes |
|---|---|---|---|
| Payment accounts | 12 | CSV captured | Includes balance and account metadata |
| Expense categories | 3 | CSV captured | Reference data |
| Expenses | 0 for 2026 view | Empty | Module enabled |
| Balance sheet | 2026 report reviewed | UI evidence captured | Assets AED 169,212.25; liabilities and owners' capital AED 59,294.19 |
| Trial balance | 24 visible accounts | XLSX captured | Debit AED 861,430.28; credit AED 820,387.73 |
| Cash flow | 4,470 entries | CSV captured and reconciled | March-September primary partitions; annual row-count variance zero |
| Profit/loss | 2026 report reviewed | Product CSV plus UI controls captured | Top gross profit AED 58,826.75; net profit AED 58,857.66 |
| Tax report | 448 input / 3,608 output rows | CSV captured | Expense tax has zero rows; annual net tax display has precision defect |

## Configuration and document evidence

- Captured 404 business-setting controls with credential and secret values excluded.
- Captured inventories for business locations, invoice schemes, barcode layouts, printers, tax rates, notification templates and subscription state.
- Six editable roles each expose 266 permission controls. Checked counts are Accounts 89, Cashier 26, Field Sales Team 51, Manager 131, Stock Transfer Coordinator 55 and Van Sales 67.
- Admin is a protected role assigned to Asas Trading and Mahi; the source exposes no editable permission form for it.
- A read-only attachment scan covered all 447 current purchase details and 2,300 of 3,572 current sale details. It found no downloadable document link. Two purchase payment notes say a voucher was attached, but the UI detail contains no corresponding attachment link.

## Current reconciliation controls

- Sales detail: 8,192 month rows plus 274 boundary rows = 8,466 annual UI rows; variance zero.
- Sales detail contains 3,569 distinct invoice references. Three were created after the earlier header export, demonstrating live-source drift.
- Purchase detail: 1,063 lines across 445 distinct references; the reference set matches purchase headers after trimming presentation whitespace.
- Purchase payment ledger: AED 498,516.40. Purchase total AED 530,187.06 less the footer due AED 31,670.66 equals the same amount.
- Sales payment ledger: AED 362,482.13, which is AED 373.50 above the earlier sales-header paid total because the source continued changing during extraction.
- Current stock: 1,202 business rows, four negative-stock rows and three rows without location assignment.
- Cash flow: 4,470 primary rows from March 31 through September 8; AED 1,134,439.11 debit and AED 1,002,844.33 credit in the exported row fields.
- Tax ledgers: input tax AED 24,907.69 and output tax AED 20,247.93. The displayed annual net tax differs because returns/adjustments are included outside those two footer totals and the result is not rounded.
- Trial balance: debit AED 861,430.28, credit AED 820,387.73, difference AED 41,042.55.
- Balance sheet: assets AED 169,212.25, liabilities and owners' capital AED 59,294.19, difference AED 109,918.06.

Additional reports include purchase/sale, customer/supplier, stock, adjustments, trending products, item movements, product purchase/sale, payment reports, register, sales representative, activity log, van stock, deleted returns, field visits, and business reports.

## Delivery, field force and routing

- Delivery active orders, scheduled orders, completed orders, drivers, pending delivery items, assignment, POD, collection and delivery-slot data.
- Field-force visits and summary counters.
- Route planning, assigned routes and visited customers.
- Seven zones, captured by CSV.

## HRM and payroll

| Area | Visible records | Export status | Notes |
|---|---:|---|---|
| Employees/users | 16 | Covered by user export | HRM dashboard count agrees with users |
| Attendance | 182 for 2026 | CSV captured | Date, employee, clocks, duration, IP and shift |
| Shifts | 1 | CSV captured | Shift definition |
| Sales targets | 16 | CSV captured | One visible row per user |
| Leave types | 0 | Empty | Module enabled |
| Leave | 0 for 2026 view | Empty | Approval/status workflow enabled |
| Holidays | 0 for 2026 view | Empty | Module enabled |
| Payroll | 0 visible | Empty | Payroll, payroll groups and additions/deductions enabled |
| My payrolls | 0 visible | Empty | Employee self-service view enabled |

## Extraction rule

An export is complete only when filters are recorded, the table is no longer processing, the page-size control is set to All, and the displayed count equals the loaded row count. Footer and totals rows remain in raw evidence but must be removed in derived staging data.
