# Domestic ERP approval packet — technical review, 2026-09-29

## Decision: NO-GO for production posting

AI-assisted review has now recorded **175 of 188** operational promotion exceptions as evidence-backed, non-posting dispositions. **13 remain open.** The immutable staging discrepancy queue still retains all 188 original findings; its count is not the count of unreviewed operational exceptions. The promotion batch `HISTORY-D7AB786EB3D6-A42462C335C2` remains `planned`, with 42,107 expected source records, **0 mapped**, no approver, and `posting_enabled=false`. These facts make production activation and final business acceptance premature regardless of unit-test success.

Seven operational decisions were added in this review: #178 (zero-quantity locationless stock excluded), #64/#65 (pending transfer retained without stock posting), #50 (product-specific 6 Pack/Carton conversion proved for one return line), and #83/#84/#85 (purchase financial reviews linked to verified gross-cost treatments with no input-VAT claim). Each decision is tied to checksum-preserved source files and an append-only operational audit event. No BizModo source row, immutable staging finding, or historical posting was changed.

## Thirteen open exceptions: six review packages

| Package | Queue IDs | Evidence established | Decision or evidence still required |
|---|---|---|---|
| Sale `AK2026-00479` | 81, 123 | Source sale/tax total AED 247.75; two receipts total AED 248.00; source due is zero. | Finance must determine the AED 0.25 overpayment/credit treatment and prove the target AR position. Do not silently write off or create a receipt. |
| Purchase `PO2026/0134` | 92, 134, 162 | Item line AED 23.10; source header/payment AED 22.97; no deterministically linked tax evidence. | Finance must identify the AED 0.13 difference and approve the journal/VAT treatment. Do not infer a discount or input-VAT claim. |
| Payment `PP2026/0010` | 141 | Purchase payment register shows AED 635.34; no matching captured cash-flow row was proven. | Recover source ledger/cash evidence or approve a documented non-posting historical exception. Do not manufacture cash. |
| Trial balance and control totals | 150, 153–156 | 46 rows lack a usable account label; VAT, customer AR, supplier AP and top-level trial controls show variances in the preserved capture. | Obtain a labeled final ledger and reconcile each control before opening balances or ledger activation. Do not assign accounts from a text guess. |
| Duplicate sale reference `AK2026-03080` | 170 | Two source sales have different source IDs, customers, locations, dates and amounts (AED 83.00 and AED 203.75). | Preserve both source identities; approve the legacy-reference display/lookup rule and verify every downstream link by identity, not number alone. |
| Duplicate purchase reference `PO2026/0339` | 171 | Two source purchases have different source IDs, suppliers, dates and amounts (AED 231.00 and AED 195.30). | Preserve both source identities; approve the legacy-reference display/lookup rule and verify payment/return links by identity. |

The amounts above are observations from the preserved export, **not** proposed journal entries or authorized adjustments. Resolution of an exception is a review disposition, not promotion, posting, filing, or approval.

## Remaining acceptance sequence

1. Obtain an atomic final **read-only** BizModo capture under a business freeze, or explicitly document why that cannot be produced. Compare source IDs, row counts, hashes, document totals and later activity against the preserved snapshots.
2. Produce reviewed target-side rules and supporting evidence for each of the six packages; record named finance/inventory decisions and independent approval where the workflow requires it. Keep unresolved rows quarantined and posting disabled.
3. Rehearse complete promotion into a fresh operational database. Reconcile all expected source records, exception decisions, inventory quantities by product/location/UOM, AR/AP, bank/cash and ledger control totals. Prove backup and restore and test rollback without overwriting newer transactions.
4. Run full automated regression, authenticated browser workflows, permissions/segregation, security and named business UAT against the release candidate. Retest the exact final image and database schema together.
5. Deploy an approval environment **with posting disabled** only after the infrastructure is specified (host, TLS, secret manager, monitoring and recovery target). Present this packet and the measured reconciliation to the accountable approver. Enable posting only through the explicit activation controls after a genuine go decision.

An AI agent may prepare and execute technical acceptance checks under authorization, but a check must fail when evidence is missing. Permission to work is not evidence that the financial controls balance or that a separate maker-checker approval occurred.
