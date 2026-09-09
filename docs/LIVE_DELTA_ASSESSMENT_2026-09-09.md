# Live delta assessment - 2026-09-09

## Outcome

A read-only browser comparison was completed against the preserved `source_exports/2026-09-08` baseline. No source record was created, edited, deleted, posted, or saved. No observed delta was imported into either clone database.

This is a UI-count and key assessment, not an atomic database backup or a complete replacement export.

## Register reconciliation

| Register | Preserved baseline | Live source | Delta | Result |
| --- | ---: | ---: | ---: | --- |
| Suppliers | 88 | 88 | 0 | unchanged |
| Customers | 793 | 794 | +1 | changed |
| Products | 464 | 465 | +1 | changed |
| Purchases, 2026 | 446 | 447 | +1 | changed |
| Sales, 2026 | 3,567 | 3,582 | +15 | changed |
| Sales returns, 2026 | 38 | 38 | 0 | unchanged |
| Purchase returns, 2026 | 9 | 9 | 0 | unchanged |
| Stock transfers, 2026 | 916 in the original CSV; 917 in the later preserved detail capture | 917 | 0 versus latest evidence | reconciled to latest capture |

The live system therefore contains 18 additional master or transaction header records relative to the original baseline: one customer, one product, one purchase, and fifteen sales. Child rows such as sale lines, purchase lines, payments, stock movements, tax entries, and accounting effects are not included in that header count.

## Identified new keys

- Customer: `CO0892`, `Al sahwat cafeteria`, added 2026-09-08 22:25 in the source UI.
- Product: SKU `98081`, `Clear Tape 100 yard (1x36pcs)`.
- Purchase: `PO2026/0456`, dated 2026-09-08 20:15, supplier reference `S5613`, gross amount AED 65.00.
- Sales: the fifteen consecutive invoice keys `AK2026-03607` through `AK2026-03621`.

The purchase detail view showed one carton of SKU `98081`, net AED 61.90, VAT AED 3.10, total AED 65.00, and no payment recorded at capture time.

## Export attempt and limitation

The source's `Export to CSV` control was invoked on a register page, but no new file appeared in the browser download location. Accordingly, no fresh CSV is represented as captured and no partial UI observation has been treated as a complete data export.

As a controlled fallback, all fifteen new sale detail views were captured to `source_exports/2026-09-09-ui-delta/sales_details.json`. The package contains 15 unique invoice keys, 35 product rows, 8 payment rows, and the displayed total/activity rows. Reconciliation is:

- total payable: AED 1,784.75;
- total paid: AED 591.00;
- total remaining: AED 1,193.75;
- payable minus paid minus remaining: AED 0.00.

Package SHA-256: `CB595C071C0C72EAF4F4B7A4FA76EAE384E896F2A759191D1440FF5F894ADB2A`.

This UI-derived package improves the evidence set but is deliberately marked `atomic: false`, `source_mutation: false`, and `clone_mutation: false`. It is not sufficient for import because customer identifiers plus stock and accounting postings still require controlled exports.

The remaining changed master/purchase records were captured to `source_exports/2026-09-09-ui-delta/master_purchase_details.json` (SHA-256 `845C78C04CA54283268DC59E0DB89EFF470EC143ED22C941BFE0997899E18F2E`). It preserves the visible fields for customer `CO0892`, product `98081`, purchase `PO2026/0456`, their purchase line and totals, and the product stock rows.

Relationship reconciliation also confirmed that SKU `98081` was transferred from Asas General Trading LLC to DXB as one carton on `ST2026/0927`. That completed transfer was already preserved in `source_exports/2026-09-08/stock_transfer_details_0001_0050.json`, closing the previously documented unmatched product/transfer relationship.

Downstream financial controls were captured in `source_exports/2026-09-09-ui-delta/financial_effects.json` (SHA-256 `E0620FE59E166A0B91A8AC8B13F449006F2BB7F93F4DEB3E8844C57F6EAC16E0`). The package contains the 12 new sales-payment rows, the matching 12 cash-flow rows, the 12 output-VAT rows added after the tax baseline, and current profit/loss and trial-balance controls.

- Sales payments: 3,653 baseline to 3,665 live; 12 receipts totaling AED 934.50.
- Cash flow: 4,470 baseline to 4,482 live; the same 12 references credit AED 934.50.
- Purchase payments: unchanged at 413; `PO2026/0456` remains unpaid.
- Input VAT: unchanged at 448 rows.
- Output VAT: 3,608 baseline to 3,620 live; 12 rows totaling AED 62.81 VAT.
- Cash-flow final balance: AED -131,594.78 baseline to AED -130,660.28 live, exactly AED 934.50 movement.
- Source trial-balance view: debit AED 295,685.66 and credit AED 31,735.66 as of 2026-09-09; it remains unfit for opening-GL migration.

An isolated merge simulation was subsequently completed against a read-only backup of the preserved clone. It produced 95 plan rows: 82 inserts, 12 safe reuses, zero updates, and one blocked conflict. No existing business-table count changed. The conflict is the earlier unlocated zero-stock row for SKU `98081`; it must be reconciled against a controlled full stock export before any real merge. See `DELTA_MERGE_SIMULATION_CHECKPOINT.md`.

The subsequent read-only stock-report export resolved that conflict. It confirms zero cartons at Asas General Trading LLC and one carton at DXB, matching transfer `ST2026/0927`. The rerun contains 82 inserts, 13 safe reuses, zero updates, and zero conflicts; the earlier unlocated zero-quantity row remains preserved as legacy evidence. See `STOCK_LOCATION_RECONCILIATION_CHECKPOINT.md`.

Before a safe delta import, fresh read-only exports are still required for the changed registers and their dependent data:

- customers and products;
- sales headers, sales lines, and sales payments;
- purchase headers, purchase lines, and purchase payments;
- current stock by location and item traceability;
- September cash-flow, tax input/output, and profit/product reports needed to reconcile downstream financial effects.

Each fresh export must be written to a new dated folder, hashed, row-counted, key-compared with the preserved baseline, and reconciled before any clone update. The 2026-09-08 baseline must remain immutable.

## Runtime safety check

- The read-only PostgreSQL clone validation service is healthy on `127.0.0.1:18081`.
- Port `18082` has no listener; disabled UAT was not restarted.
- The source and clone were not mutated during this assessment.

## Migration gate

Status: **delta detected; import blocked pending complete fresh exports and reconciliation**.

Username/password browser access can support controlled exports and record-level checks, but it cannot guarantee an atomic no-data-loss copy while users continue posting transactions. Final cutover still requires either a source database plus uploaded-file backup or a transaction-free capture window followed by final reconciliation.
