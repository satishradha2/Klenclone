# Cutover capture rehearsal checkpoint

Execution ID (UTC): `20260908T224857Z`  
Status: **rehearsal complete; not a final atomic capture**

## Outcome

All currently preserved browser evidence was packaged through the same checksum-first workflow intended for the final cutover. The archive is:

`var/cutover_rehearsals/20260908T224857Z/cutover-rehearsal.zip`

SHA-256:

`C144FB58815C95B0ACAEAD89CC1EB075DE14ACECCF11C7340535E3D52DC00A40`

| Control | Result |
| --- | ---: |
| Evidence files | 92 |
| Internal capture manifest | 1 |
| Total ZIP members | 93 |
| Uncompressed evidence bytes | 12,930,151 |
| ZIP integrity errors | 0 |
| Source evidence changed | No |
| Merge allowed | No |
| Posting enabled | No |

## Package controls

- Every baseline and delta file has an individual SHA-256 entry in `capture-manifest.json`.
- ZIP members were read back and matched to their source hashes before the temporary archive was promoted to its final local name.
- Existing output paths cannot be overwritten.
- A failure removes only the newly created temporary archive.
- HRM data is packaged as archive-only evidence and remains excluded from the operational ERP.
- Uploaded-file completeness remains false because the browser does not expose a complete attachment archive.

## Qualification

This archive is deliberately labeled `non_atomic_cutover_rehearsal`. It proves that the local packaging, hashing, inventory and verification procedure works. It does not prove that BizModo was transaction-free while the original exports were created, so it cannot authorize a real merge.

The same workflow can create the final browser-only package after all source-system users stop transactions and that freeze is confirmed. For the strongest no-data-loss result, a hosting-provider database and uploaded-file backup remains preferred.

## Verification

- Focused rehearsal tests: 2 passed.
- Complete project suite: 67 passed, 1 PostgreSQL-environment test skipped.
- Source BizModo was not written to.
- Preserved clone was not modified.
- Port 18081 remains read-only and non-posting.
- Port 18082 remains disabled.
