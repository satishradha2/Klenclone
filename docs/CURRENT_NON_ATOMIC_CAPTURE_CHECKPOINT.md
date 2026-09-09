# Current non-atomic source capture checkpoint

Captured at: 2026-09-09T06:30:24.859Z  
Source: BizModo V7.5.1 (`https://mart.bizmodo.io`)  
Access method: authenticated browser session using visible list registers only

## Safety and cutover status

- The source was accessed read-only. No create, update, delete, import, posting, approval, or configuration action was performed.
- The source was still active during capture. This checkpoint is therefore **non-atomic** and is **not eligible for final cutover merge**.
- HRM and payroll remain excluded from the target ERP. Previously preserved HRM evidence remains archive-only.
- Username/password-only access cannot guarantee hidden database fields, uploaded files, attachments, or a transaction-consistent point-in-time copy.

## Verified capture

| Register | Prior watermark | Current rows | Change |
|---|---:|---:|---:|
| Sales (2026) | 3,582 | 3,584 | +2 |
| Purchases | 447 | 447 | 0 |
| Products | 465 | 465 | 0 |
| Customers | 794 | 794 | 0 |
| Suppliers | 88 | 88 | 0 |
| Stock transfers (2026) | 917 | 920 | +3 |
| Sales payments | 3,665 | 3,665 | 0 |
| Purchase payments | 413 | 413 | 0 |
| Sales returns (2026) | 38 | 38 | 0 |
| Purchase returns (2026) | 9 | 9 | 0 |

All ten CSV files passed independent SHA-256 verification. Each CSV contains exactly one header row plus the current row count shown above. The authoritative package metadata is in `source_exports/2026-09-09-current-non-atomic/CAPTURE_STATUS.json`; file hashes are in `source_exports/2026-09-09-current-non-atomic/SHA256SUMS.txt`.

The reusable `validate-capture` control was then run against the sealed directory. All seven controls passed with zero failures, the source package hashes remained unchanged, and the resulting report is `var/capture_validations/20260909T063024Z/capture-validation.json` (SHA-256 `111F5DBD0756A7C0427853F6D3D0FB4D1EEAE36878C1300117296F28EA09ABC9`). The full automated suite completed with 72 passed and 1 skipped test.

## Reconciliation decision

The +2 sales and +3 stock-transfer movement proves that the earlier watermark is stale and the source has not been frozen. These files are retained as a traceable evidence checkpoint only. They must not overwrite the preserved clone or be applied as a final delta.

Observed movement references:

- Sales: `AK2026-03622` at 09/09/2026 09:45 and `AK2026-03623` at 09/09/2026 09:46; both displayed as Due.
- Stock transfers: `ST2026/0928`, `ST2026/0929`, and `ST2026/0930`; all displayed as Completed.

A formal closing-rehearsal watermark was derived from the sealed package and compared with the pre-freeze watermark. The comparison reports `activity_detected` for exactly `sales` and `stock_transfers`; transaction-free confirmation, final capture, merge, and posting all remain false.

- Closing watermark: `var/activity_watermarks/20260909T063024Z/closing-rehearsal-watermark.json` (SHA-256 `5E5011C81FA07C81CB663C7B8D2EDC53076AA89A77950FC645EA8FB14055023B`)
- Drift comparison: `var/activity_watermarks/20260909T063024Z/drift-comparison.json` (SHA-256 `37EDB447100B62835521C566BE7D8731DC5A0DF4EBFB431259A1FB93FE15D1B6`)
- Automated suite after adding the reusable capture-watermark builder: 74 passed, 1 skipped.

## Required next gate

Obtain a short transaction-free window, capture a second watermark and the same registers, and require zero movement between the start and end watermarks. Only after that zero-drift check should the delta importer and merge simulation be rerun for final cutover approval.
