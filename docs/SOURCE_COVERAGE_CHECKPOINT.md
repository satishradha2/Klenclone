# Source coverage checkpoint

## Result

Every imported source row now has an explicit target coverage decision for snapshot `bizmodo-2026-09-08-browser`. The process used only local evidence and did not connect to or modify live BizModo.

| Coverage status | Rows |
|---|---:|
| Structured canonical link | 31,487 |
| Linked control/report evidence | 3,393 |
| Preserved control/configuration evidence | 6,339 |
| Structured promotion required | 0 |
| HRM archival-only preservation | 183 |
| Presentation/footer quarantine | 42 |
| Unclassified | 0 |
| Uncovered | 0 |
| **Total** | **41,444** |

The coverage table has 41,444 rows for 41,444 raw records. Every row retains the immutable raw-record ID and content-hash registry trail.

## Reference masters

Forty-four simple reference records were promoted without enabling them:

- 19 brands.
- Eight categories.
- Seven industries.
- Three expense categories.
- Seven delivery zones.

Source codes are retained where present; otherwise a stable staging code is generated from the captured name and raw identity. All reference masters remain migration-locked.

## Residual evidence

There are 10,026 historical residual records, all accounted for:

- 9,732 alternate reports, control extracts or configuration evidence.
- 69 operational records subsequently promoted to dedicated locked models; their residual rows remain as historical evidence.
- 183 attendance/shift rows retained as HRM archival evidence.
- 42 presentation/footer rows retained in quarantine.

Residual records store the immutable content hash, source locator, source keys and any canonical target links. Their raw payloads remain in the protected raw layer; they have not been dropped or rewritten.

## Structured promotion follow-up

All 43 entity coverage gates are now `covered_locked`. The 69 previously blocked rows were promoted as follows:

| Entity | Rows | Dedicated treatment |
|---|---:|---|
| Contact login | 33 | Disabled portal identities without passwords |
| Sales drafts | 7 | Locked draft workflow records |
| Sales quotations | 7 | Locked quotation workflow records |
| Sales targets | 16 | User-linked evidence; amount/period unavailable |
| Shipments | 4 | Locked shipment records linked to invoices |
| Stock-transfer detail | 2 | Hash-preserved, parse-blocked artifacts |

Record-level workflow gates remain blocked where relationships, credentials, target definitions or transfer parsing are unresolved. Covered does not mean activated; it means every row has an explicit, auditable structure and treatment.

## Classification correction and rebuild

The first local coverage calculation mislabeled 354 supplemental cash-flow boundary rows and two stock-transfer detail gaps as unclassified. The classification was corrected. Only the derived local coverage tables were removed and regenerated: 41,444 coverage rows, 43 gates, 10,026 residual rows and one coverage audit event. Raw evidence removed: zero. The regenerated tables are fully recoverable from the immutable registry and now contain zero unclassified rows.

## Verification

- Coverage: 41,444 / 41,444.
- Uncovered and unclassified rows: 0.
- Activation-enabled coverage rows: 0.
- A repeated `coverage` run created zero records.
- `python -m pytest -q` passes 39 tests, compilation succeeds, and reconciliation includes every coverage table.

This checkpoint proves row-level treatment of the accessible exports, not atomic completeness of the live system. A frozen final extraction and delta reconciliation remain mandatory because username/password browser exports cannot prove hidden, deleted, attachment or concurrent-transaction coverage.
