# Van sales and offline field-operation checkpoint — 21 September 2026

## Implemented

- Dated route plans linked to governed van masters and customer stops.
- Device assignment and one open route per van/date.
- Load-out capture using locked product/UOM snapshots and available-stock validation.
- Independent load approval before a route can start.
- Idempotent offline synchronization using device ID plus client reference.
- Offline sales, customer returns and collections with VAT/payment evidence.
- Expected cash calculation, counted cash, variance and independent route-close approval.
- Append-only operational audit events for every controlled transition.

## Safety boundary

This is controlled staging and test data only. Load-out, offline transactions and route close do not change permanent stock or create accounting postings. BizModo remains read-only. All target test rows will be deleted before the final fresh import.

## Verification

- Migration registry: `0048`
- Van operational tables: 5
- Targeted workflow/security tests: 16 passed
- Live preview health: healthy on `127.0.0.1:18082`
- Integrated posting batches after deployment: 0
