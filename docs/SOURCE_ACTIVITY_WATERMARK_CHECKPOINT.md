# Source activity watermark checkpoint

Capture time (UTC): `2026-09-08T22:55:18Z`  
Status: **pre-freeze watermark captured; final capture still disabled**

## Outcome

The authenticated BizModo V7.5.1 registers were inspected read-only and a pre-freeze activity watermark was recorded at:

`source_exports/2026-09-09-pre-freeze-watermark/live_activity_watermark.json`

SHA-256:

`95A3A8773AFF37B06588DD893D1EAF726745792ABAF78948B9A8EC45B678025F`

## Reliable live watermarks

| Stream | Visible count | Latest evidence |
| --- | ---: | --- |
| Sales | 3,582 | `AK2026-03621`, 09/08/2026 23:26 |
| Purchases | 447 | `PO2026/0456`, 09/08/2026 20:15 |
| Products | 465 | SKU `98081` present |
| Customers | 794 | `CO0892` present |
| Suppliers | 88 | Register total |
| Stock transfers | 917 | `ST2026/0927`, 09/08/2026 20:19 |
| Sales payments | 3,665 | `SP2026/3777`, 09/08/2026 23:33 |
| Purchase payments | 413 | `PP2026/0442`, 09/08/2026 17:03 |
| Sales returns | 38 | `CN2026/0039`, 09/08/2026 18:33 |
| Purchase returns | 9 | `2026/0012`, 08/26/2026 15:39 |

The core document/master counts agree with the zero-conflict simulation projection: 3,582 sales, 447 purchases, 465 products and 917 transfers.

## Limited registers

The POS, expense and stock-adjustment registers returned zero visible rows under the current authenticated view despite earlier preserved exports containing data. Those values are marked `reliable=false`; they are not interpreted as authoritative zero balances and require fresh controlled exports during cutover.

## Comparator

The new `compare-watermarks` command compares opening and closing counts plus latest keys. Any change returns `activity_detected` and a non-zero CLI exit. Stable values do not by themselves authorize a final capture unless both markers explicitly confirm a transaction-free window.

The self-check artifact is:

`var/activity_watermarks/20260908T225620Z/pre-freeze-self-check.json`

SHA-256:

`7E171F8218A7ECCC7F7C2CB4D34A898A6725D3E1EA9A420E991F3A006F0F9AB5`

It reports stable watermarks but correctly retains:

- `transaction_free_window_confirmed=false`
- `final_capture_allowed=false`
- `merge_allowed=false`
- `posting_enabled=false`

## Verification

- Focused watermark tests: 2 passed.
- Complete project suite: 69 passed, 1 PostgreSQL-environment test skipped.
- No source data was created, edited, deleted or posted.
- The preserved clone was not modified.
- Port 18081 remains read-only and non-posting.
- Port 18082 remains disabled.

The next marker must be captured after the business confirms that all BizModo transactions have stopped. It must then bracket the complete fresh export run; any opening/closing difference invalidates that run.
