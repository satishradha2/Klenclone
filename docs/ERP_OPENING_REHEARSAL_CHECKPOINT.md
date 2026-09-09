# ERP opening-balance rehearsal checkpoint

> **RETRACTED — cross-project target.** This checkpoint used the separate `D:\Klen+ ERP` staging schema and is not completion evidence for the BizModo clone. See `docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md`.

Checkpoint time: 2026-09-09 UTC

## Outcome

The available BizModo data has been transformed into source-keyed opening receivables, opening payables, and provisional location-level stock templates. The package is checksum-bound and has passed isolated ERP validation. Matching non-posting batches have also been placed in operational ERP staging. BizModo was not changed and no ERP invoice, journal, stock movement, or inventory balance was posted.

## Canonical package

- Package: `var/erp_opening_rehearsals/20260909T094924Z/package-v2`
- Package manifest SHA-256: `F7708A45BB3B52677F1CEB909045A6C9E90A220D9F473C7E7D0FBB698556BD3D`
- Isolated validation: `var/erp_opening_rehearsals/20260909T094924Z/package-v2-isolated-validation.json`
- Isolated validation SHA-256: `22DD8E18029BAF1B2769C9B9414F883DC832376434F136D80FE10B25E6B80527`
- Isolated result: 814 of 814 rows valid; zero errors and zero duplicates; business-table counts unchanged.

## Prepared balances

| Layer | Rows | Prepared control total |
| --- | ---: | ---: |
| Opening receivables | 199 | AED 63,159.66 |
| Opening payables | 53 | AED 30,737.85 |
| Provisional opening stock | 562 | 29,265.02 base units |

Contact-ID-linked balances are used for AR/AP. Negative net balances are deliberately deferred for advance/contra-account review: eight customers and six suppliers. Four negative stock rows, three missing-location rows, and the report's `Total:` summary row are also excluded and recorded in `exceptions.json`.

## Reconciliation limitations

- Positive customer contact balances are AED 906.59 below the summed sales-header due amount.
- Positive supplier contact balances are AED 1,449.56 below the summed purchase-header due amount.
- The baseline stock snapshot totals 29,252.02 base units, while the current product register totals 29,094.02, a decrease of 158.00.
- Because negative baseline rows cannot be imported through the positive-opening template, the provisional positive stock package totals 29,265.02. The required aggregate correction from that provisional amount to the current register is therefore **-171.00**, across 26 SKUs.
- Current location-level quantities were not available. `stock_delta_required.json` is an aggregate SKU correction schedule; location distribution still requires a later fresh capture or reviewed allocation.

These variances remain visible and are not guessed away. They prevent this checkpoint from being described as a final no-data-loss cutover.

## Staging placement

- Pre-placement database backup: `var/erp_opening_rehearsals/20260909T094924Z/pre-opening-batches-staging.dump`
- Backup SHA-256: `789B2030186D7C45EBB3D4761FC049C65C84AD547E8C438846AC934F290B9D34`
- Operational validation report: `var/erp_opening_rehearsals/20260909T094924Z/operational-staging-validation.json`
- Operational validation SHA-256: `46E21FB34922B5B965D7CAC157215D10CFF3B3154E92DB5BD768B7358B844D56`
- Batches: `ROPN-20260909095445-1` through `ROPN-20260909095445-3`, all `validated`, not submitted, approved, or posted.
- Branch/warehouse mappings created in staging: BL0001, RAK, and DXB; source BL0002 maps to existing SHJ / MAIN / STORAGE.

The three import CSV files in package v1 and canonical package v2 have identical SHA-256 hashes. Version 2 corrects only the later-delta reconciliation metadata.

## ERP validator correction

Opening-stock duplicate detection incorrectly treated SKU alone as the unique key, rejecting a product held in multiple warehouses. The validator now keys opening stock by SKU, warehouse, location, and lot. Price-list duplicate detection was corrected at the same time to include price list, SKU, UOM, and minimum quantity. The local staging backend was rebuilt and reports ready after the change.

## Gate for the next step

Operational posting remains intentionally disabled for this checkpoint. The next controlled step is a staging-only posting rehearsal from the three validated batches, followed by journal, invoice, inventory, and rollback reconciliation. It must retain the provisional label and the later-delta requirement; it is not production authorization.
