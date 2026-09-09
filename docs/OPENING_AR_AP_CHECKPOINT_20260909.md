# Opening AR/AP checkpoint

Date: 2026-09-09

## Outcome

Checksum-bound contact-level opening receivables, payables and partner advances
have been imported into the isolated Asas operational database. They are staged
controls only: no journal, invoice, payment allocation or source-system entry
was posted. BizModo was not modified.

Migration `0007` creates an opening-balance batch, positive party-balance rows,
and a separate financial-exception ledger. The imported batch key is
`f94c5e10d70f91c57b99a291c4f409f7a131cd2fbf3b066ad1b782de51e6393a`.

## Staged controls

| Balance type | Parties | Amount |
| --- | ---: | ---: |
| Receivable | 196 | AED 62,680.16 |
| Customer advance | 9 | AED 681.86 |
| Payable | 53 | AED 31,665.00 |
| Supplier advance | 6 | AED 133.04 |

Net customer position is AED 61,998.30 receivable. Net supplier position is
AED 31,531.96 payable. Every row retains the source Contact ID, name snapshot,
control account and opening-offset account. The database prohibits non-positive
rows and enforces `posting_enabled=false`.

## Open reconciliation exceptions

| Control | Contact-master amount | Comparison amount | Variance |
| --- | ---: | ---: | ---: |
| Customer header due | AED 61,998.30 | AED 63,890.51 | AED -1,892.21 |
| Supplier header due | AED 31,531.96 | AED 31,983.71 | AED -451.75 |
| Combined YTD due | AED 30,466.34 | AED 31,221.05 | AED -754.71 |

These are preserved as open exceptions because the browser exports were
sequential and report semantics differ. The contact master is the staged
control source, but exact invoice ageing and payment allocation are not claimed.

## Verification

- Repeat import returned `already_imported`; party-balance row count stayed 264
- All 264 rows remain non-posting
- Open financial exceptions: 3
- Quarantined stock exceptions: 4 totaling -13.00 units
- Permanent journal batches: 0
- Operational drafts: 0
- Browser smoke test shows all four staged groups and three open exceptions
- Automated suite: 88 passed, 1 expected isolated-PostgreSQL skip
- Application health: operational database reachable; posting disabled

## Backup and restore

- Backup: `var/backups/asas-operational-opening-balances-20260909.dump`
- Size: 98,555 bytes
- SHA-256: `EF8B9AE741F69EB1C7B4598FA202A5E23A3F173373FFF084FFC1D635E40642F7`
- Restore verified migration 0007, all four balance groups, three financial
  exceptions, 579 stock positions, four stock exceptions and zero journals
- Temporary restore database removed after verification

## Live delta status

The BizModo session was renewed and a read-only header watermark was captured.
The source advanced during capture, so the resulting package is explicitly
non-atomic and blocked from merge. See `LIVE_DELTA_WATERMARK_20260909T133953Z.md`.

## Remaining gates

1. Refresh the signed-in BizModo session and capture new sales, purchase,
   return, stock and partner-balance watermarks.
2. Reconcile the new delta against this staged batch.
3. Resolve or explicitly accept the three financial and four stock exceptions.
4. Perform the final transaction-free capture and cutover reconciliation.
