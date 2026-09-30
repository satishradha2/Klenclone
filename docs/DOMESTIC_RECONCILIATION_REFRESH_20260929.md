# Domestic source-to-target reconciliation refresh — 2026-09-29

## Scope and evidence boundary

This is a rerun of the existing `bizmodo-2026-09-08-browser` clone snapshot, **not** a new extraction from live BizModo. The snapshot was created at 2026-09-08 17:36:35 UTC and is marked non-atomic. Its 86 file manifests produce SHA-256 `7adfc6c22c66f84b0920b8ef99cf1f12c829a679bacaefe0251823a0c7f7c566` when their path, hash, and source-row count are combined by the audit exporter.

Before rerunning reconciliation, the clone PostgreSQL database was backed up to `var/domestic-reconciliation-20260929/clone-before.dump` (SHA-256 `605B2A0F2CF08637392DC1DA526B23F35A0580E919922ED20C2165FF613E69DB`). That backup was restored into the **separate** `klen_domestic_reconcile_20260929` database. `python -m klen_clone.cli reconcile --snapshot bizmodo-2026-09-08-browser` completed successfully against only that isolated database. The original clone's 21 grouped migration-queue states and 17 grouped reconciliation-finding states matched the isolated rerun exactly. Neither the BizModo source nor the shared clone database was changed for this audit.

The repeatable, read-only export command is `python -m klen_clone.domestic_release_audit --snapshot bizmodo-2026-09-08-browser --output-dir <new-directory>` with `KLEN_DATABASE_URL` pointing to the isolated database. It creates `summary.json` and `blocked_queue.csv` without overwriting existing output. The final output is at `var/domestic-reconciliation-20260929/audit-3/`; the CSV SHA-256 is `14780132F6C65CBBDA34C02A78717334010FB4DA148E1344E4497D183878D266`.

## Current release gate

| Area | Blocked migration queue items |
|---|---:|
| Finance and accounting | 90 |
| Inventory and UOM | 61 |
| Transaction/master relationships | 37 |
| **Total** | **188** |

There are also 95 open reconciliation findings. They overlap the migration queue and **must not be added** to the 188. All 188 records in this **immutable staging queue** remain open and activation-blocked; this queue preserves the original findings. It is not the current count of outstanding operational review decisions.

### Operational review status — corrected 2026-09-29

The separate `HISTORY-D7AB786EB3D6-A42462C335C2` operational promotion batch contains the same 188 exception identities. Before this refresh, its audit trail already showed **168 resolved, 20 open** using checksum-verified later captures and controlled non-posting classifications. This was omitted from the initial refresh conclusion and must not be mistaken for 188 unreviewed items. The first update resolved exception **#178**: the earlier locationless SKU `98081` row has quantity zero, and later product/location totals reconcile. Its resolution carries the earlier stock-file checksum and supporting evidence #188, and explicitly excludes the zero row from stock posting.

A further evidence pass resolved six more **non-posting review dispositions**: #64 and #65 are the two sides of transfer `ST2026/0141`, whose frozen header and preserved detail both say `Pending`; #50 is the `CN2026/0010` tissue return for which two product captures independently prove **6 Packs per Carton**, giving 0.50 Carton = 3.00 Packs; #83–#85 link their financial-document reviews to already verified gross-cost classifications for `PO2026/0454`, `PO2026/0433`, and `PO2026/0432`, with **no synthetic input-VAT claim**. Each was recorded in the operational audit trail with source-file checksums. The current operational queue is **175 resolved, 13 open**.

The batch itself is still `planned`, with 42,107 expected source records, **zero mapped records**, no approver, and posting disabled. An operational exception marked `resolved` means its review evidence/disposition is recorded; it does **not** mean historical records were promoted, posted, or signed off for go-live.

The 13 open operational IDs are `81, 92, 123, 134, 141, 150, 153, 154, 155, 156, 162, 170, 171`. They form six business decision packages: sale `AK2026-00479` (#81, #123); purchase `PO2026/0134` (#92, #134, #162); payment `PP2026/0010` (#141); trial-balance labeling and four control variances (#150, #153–#156); and two duplicate source document numbers (#170, #171). None should be silently posted or assigned a speculative match.

The 188-row CSV includes queue ID, source kind and ID, source reference, raw-record ID where available, SKU/UOM where available, severity, assigned owner role, required action, and original evidence. A blank source field means the staged evidence did not provide it; it is not an invitation to infer it.

## Decision queue by action

| Needed action | Items | Owner |
|---|---:|---|
| Reconcile source document, cash, and ledger evidence | 90 | Finance |
| Approve product-specific factor-to-base snapshots | 25 | Product/UOM |
| Recapture or identify inventory source headers | 15 | Inventory |
| Approve source-to-target relationships or document-number treatment | 15 | Sales/procurement |
| Recapture or identify transaction-line headers | 12 | Sales/procurement |
| Reconcile stock and location evidence | 12 | Inventory |
| Resolve product identity using source evidence | 10 | Product master |
| Approve product-specific UOM definitions/conversions | 9 | Product/UOM |

The 40 `INVENTORY_MOVEMENT_READINESS` items divide into 15 missing/unreliable source headers and 25 unapproved UOM conversions. The 22 `TRANSACTION_LINE_RELATIONSHIP` items divide into 11 document lines without a resolved product and 11 sale lines without a resolved parent document; one of the product-unresolved lines also lacks a resolved header, hence the action totals above include 12 header decisions and 10 product decisions.

For the 11 product-unresolved document lines, ten source SKUs are blank; the one populated SKU has no canonical product in this snapshot. Exact normalized name matching yields no match for nine and two candidates each for the other two—none supplies a unique, supportable link. Observed global UOM labels such as carton, pack, and bundle have conflicting base units/factors, so a global conversion would silently change quantities. No product identity, header, factor, ledger treatment, or posting readiness was auto-approved or changed.

## What closes this gate

1. Obtain an atomic/final BizModo read-only recapture if the source evidence can now supply missing identifiers or headers; retain the prior snapshot and its hashes for comparison.
2. Route each remaining queue item to the named business owner with supporting source evidence, a target-side decision, independent approval, and date. Apply only approved, auditable transformation rules in the clone; never edit source rows or verified raw evidence.
3. Work the **13 open operational decisions** first, with candidate evidence and independent finance review. Preserve the 175 recorded dispositions and retest their mapping/posting boundaries; do not merely clear the immutable staging findings.
4. Rerun isolated reconciliation against a final capture, compare IDs/statuses and finance/inventory controls, then complete named business UAT. Activation remains blocked until those gates pass. The absence of historical foreign transactions is a future-proofing scenario, not a domestic discrepancy fix.
