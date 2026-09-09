# Controlled export and reconciliation checkpoint

Date: 2026-09-09

## Outcome

Seven permission-protected module review packages were generated from the isolated UAT clone. Each ZIP contains redacted CSV datasets, `reconciliation.json`, `manifest.json`, and review instructions. The manifest records the required permission, requesting synthetic identity, active location scope, per-file SHA-256 checksums, excluded sensitive fields, and the non-posting/no-mutation state.

Corrected package set: `var/business_review_packages/20260908T214704Z`

## Package coverage

| Module | Business rows | Supporting rows | Open discrepancy rows included |
|---|---:|---:|---:|
| Customers | 793 | 0 | 0 |
| Suppliers | 88 | 0 | 0 |
| Products | 464 | 464 product-UOM profiles | 0 |
| Sales | 385 documents | 821 lines; 385 payments | 120 |
| Purchases | 454 documents | 1,099 lines; 410 payments | 109 |
| Inventory | 6,048 movements | 0 | 40 |
| Accounting | 8,325 journal blueprints | 0 | 126 |

Discrepancy datasets intentionally overlap where an exception is relevant to more than one business review. They are not additive totals.

## Reconciliation highlights

- Accounting journal blueprint debits and credits both total `2,457,167.729800`; variance is `0.000000`.
- Inventory directional UOM formula mismatches are `0` using `quantity_base = entered_quantity × factor_to_base_snapshot × movement_sign`.
- Inventory has 12 incomplete rows where the source evidence does not contain all formula operands; these remain business-review items rather than being imputed.
- Sales documents total `49,995.680000`; exported lines total `49,995.590000`; payments total `37,624.120000`.
- Purchase documents total `532,614.400000`; exported lines total `506,707.350000`; payments total `497,738.390000`.

The packages preserve these differences for review and do not create balancing entries, amend transactions, or approve exceptions.

## Access and safety controls

- Unauthenticated export requests return HTTP 401.
- Every module download rechecks its specific permission.
- Sales, purchases, and inventory are filtered to the principal's allowed location IDs (`MAIN` in this UAT run).
- Contact channels, addresses, tax identifiers, password material, source payloads, and evidence JSON are excluded.
- Text that could be interpreted as a spreadsheet formula is neutralized; negative numeric values are preserved as numbers.
- Package generation runs in memory and does not modify BizModo, the clone, or operational records.
- Posting, workflow execution, approval, and assignment activation remain disabled.

## Verification

- Authenticated technical UAT: 82 passed, 0 failed, including all seven package downloads, checksum/manifest validation, and the protected synthetic review register.
- Application suite: 58 passed, 1 PostgreSQL-only test skipped outside its isolated profile.
- Browser verification: protected Exports tab rendered all seven modules and completed a customer-package download.
- PostgreSQL validation service and SQLite UAT service remain read-only and non-posting.

## Business review requirement

Module owners should compare the CSV rows and control totals to their independent source reports, record accepted variances or missing evidence, and return decisions using the package SHA-256 values from `package-index.json`. No package constitutes migration approval.
