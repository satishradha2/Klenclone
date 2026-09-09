# Live delta watermark — 2026-09-09 13:39:53 UTC

## Outcome

The renewed BizModo session was used only for read-only register inspection.
Header-level delta evidence was captured and sealed locally. BizModo was not
modified and the delta was not imported into Asas ERP.

The source changed during capture: the first sales watermark ended at
`AK2026-03640`, while the closing watermark had advanced to `AK2026-03641`.
This proves the capture is non-atomic and blocks merge/cutover.

## Changes since the sealed reconciliation capture

| Register | Prior | Current/derived | New evidence |
| --- | ---: | ---: | ---: |
| Sales | 3,591 | 3,602 estimated | 11 headers |
| Purchases | 450 | 455 | 5 headers |
| Products | 470 | 472 | 2 masters |
| Customers | 794 | 795 | 1 master |
| Suppliers | 88 | 89 | 1 master |
| Stock transfers | 920 | 932 estimated | 12 headers |
| Sales payments | 3,665 | 3,683 | 18 payments |
| Purchase payments | 413 | 414 | 1 payment |
| Sales returns | 39 | 40 estimated | 1 header |
| Purchase returns | 9 | 9 known | 0 observed today |

New sales total AED 3,745.75 with AED 3,416.00 due. New purchases total
AED 2,458.18 with AED 2,206.18 due. Purchase `PO2026/0460` is a backdated
insertion dated 8 September, demonstrating why latest-key checks alone are not
sufficient.

New masters observed:

- Products `98091` and `98092`
- Customer `CO0894`
- Supplier `CO0893`

## Package

- `source_exports/2026-09-09-live-delta-watermark-20260909T133953Z/CAPTURE_STATUS.json`
- `source_exports/2026-09-09-live-delta-watermark-20260909T133953Z/delta_headers.json`
- `source_exports/2026-09-09-live-delta-watermark-20260909T133953Z/SHA256SUMS.txt`

The package validates unique header keys and the recorded sales/purchase totals.
It deliberately has `merge_allowed=false` and `posting_enabled=false`.

## Remaining requirement

This is a watermark package, not a complete delta. Transaction lines, payment
allocations, exact location stock movements and uploaded files are still needed.
The next safe capture requires users to stop transactions for the duration of
the exports, followed immediately by a closing watermark proving no activity.

