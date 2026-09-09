# Canonical master checkpoint

## Result

Canonical ERP masters have been promoted from the typed staging layer for snapshot `bizmodo-2026-09-08-browser`. Promotion occurred only in the confidential local target database; it did not connect to or modify BizModo.

| Master/control | Source | Target | Variance |
|---|---:|---:|---:|
| Customers and suppliers | 881 | 881 | 0 |
| Products | 464 | 464 | 0 |
| UOM definitions | 202 | 202 | 0 |
| Product UOM profiles | 464 | 464 | 0 |
| Inventory opening controls | 1,206 | 1,206 | 0 |
| Tax profiles | 1 observed default VAT profile | 1 locked profile | 0 |

All 881 party records have unique captured contact IDs. All 464 products have unique captured SKUs. Records were not merged by display name, so source identity and auditability are retained.

## Controlled master states

- Parties: 881 `migration_locked_ready`.
- Products: 460 `migration_locked_ready`; four `review_required_tax_unassigned` because the source product tax field is blank.
- UOM definitions: 186 parsed package definitions; 16 base-only definitions with no invented containment factor.
- Product UOM profiles: 454 resolved, nine partially resolved, one unobserved.
- Product base factors remain identity `1`; package conversion evidence remains in immutable snapshots until approved.
- The UAE 5% VAT profile is migration-locked and requires tax-owner approval before activation.

## Opening-balance queue

The 1,206 inventory controls were copied without changing their computed evidence:

| Queue state | Count |
|---|---:|
| Pending approval | 1,178 |
| Blocked — unresolved movements | 17 |
| Blocked — negative closing quantity | 4 |
| Blocked — missing closing balance | 4 |
| Blocked — missing location | 2 |
| Blocked — unresolved product | 1 |

The customer and supplier masters contain no non-zero explicit source opening or advance balances. Current AR/AP due values remain preserved as evidence but were not relabeled as opening balances.

## Safety and verification

- Every promoted master and opening queue item is disabled operationally.
- Every opening queue item has `posting_enabled=false`.
- No blank product tax was silently converted to zero-rated or exempt.
- No partially resolved UOM was treated as approved.
- A repeated `masters` build created zero rows, proving idempotency for this snapshot.
- `python -m pytest -q` passes 31 tests, and compilation succeeds.

This checkpoint is not cutover approval. The 28 blocked inventory openings, four unassigned product taxes, and 10 unresolved/partially resolved product-UOM profiles require controlled review. Final balances still require a frozen re-export and delta reconciliation because the browser snapshot is non-atomic.
