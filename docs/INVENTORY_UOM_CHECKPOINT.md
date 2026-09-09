# Inventory and UOM reconstruction checkpoint

Snapshot: `bizmodo-2026-09-08-browser`  
Source status: Non-atomic, read-only browser snapshot

## Outcome

The staging database now contains 202 source-faithful UOM definitions, 464 product UOM profiles and 18,022 inventory movement rows. Original quantities and UOM text are retained independently from canonical quantities.

| Movement type | Rows |
|---|---:|
| Sale issue | 8,466 |
| Purchase receipt | 1,063 |
| Sale-return receipt | 44 |
| Purchase-return issue | 11 |
| Transfer out | 4,219 |
| Transfer in | 4,219 |
| Total | 18,022 |

The 45 visible purchase-return form rows remain in detail staging. Only the 11 rows with a positive returned quantity become stock movements; 34 blank or zero selection rows are retained as evidence but correctly excluded from the ledger.

## Posting control

- 18,007 movements are eligible as posted.
- 11 sale issues are held because their three sale headers were created after the earlier header export.
- Two transfer legs are held because transfer `ST2026/0927` has no header in the earlier export.
- Two transfer legs are retained as `pending_not_posted` for the single pending transfer.
- Transfers are represented as paired negative source-location and positive destination-location entries.

## Conversion control

For every converted row, `quantity_base = source_quantity × factor_to_base_snapshot × direction_multiplier`. The source quantity and source UOM are never overwritten.

| Conversion result | Movement rows |
|---|---:|
| Identity conversion | 13,035 |
| Exact source-registry conversion | 4,960 |
| Ambiguous registry definition | 9 |
| No matching conversion definition | 6 |
| Product unresolved | 7 |
| Source UOM missing | 5 |

Base quantity is available for 17,982 of the 18,007 posted movements. The remaining 25 posted rows are quarantined from base-unit stock arithmetic until the product or UOM evidence is resolved.

Exact package labels such as `Carton (20 Pack)` may use an exact registry factor. Generic aliases are never assigned a guessed multiplier. The source registry has conflicting definitions for five aliases: `bundle`, `carton`, `kg`, `pack`, and `piece`.

Four unresolved conversion pairs cover the remaining registry/no-definition cases:

- `carton (12 pc(s))` to `pack`: 2 movements.
- `carton (20 pack)` to `carton`: 4 movements.
- generic `carton` to `pack`: 5 movements.
- generic `carton` to `piece`: 4 movements.

## Product coverage

- 454 product UOM profiles are fully resolved for all observed movement units.
- 9 are partially resolved.
- 1 product has no observed 2026 movement in the extracted evidence.

## Remaining gate

This ledger reconstructs the accessible 2026 movement evidence but does not yet prove that opening stock plus movements equals the location stock snapshot. That final equation requires opening-stock history or an approved balancing-opening entry, and a frozen export is still required because the browser snapshot is non-atomic.

Document-level tax, discount, rounding, return and payment allocation is now recorded in `FINANCIAL_ALLOCATION_CHECKPOINT.md`. The next inventory gate is opening-stock and location-level closing-balance reconciliation.
