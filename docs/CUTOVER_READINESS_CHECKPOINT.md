# Cutover-readiness checkpoint

Execution ID (UTC): `20260908T224623Z`  
Status: **evidence controls passed; frozen capture pending**

## Outcome

An executable, fail-closed cutover preflight now inventories and hashes all currently preserved evidence without modifying BizModo, the staging clone, the validated delta, or the merge simulation.

The generated manifest is:

`var/cutover_readiness/20260908T224623Z/cutover-readiness.json`

SHA-256:

`1CA97D5304520E0AA3203327EC381845029A9251B2204F72EA17BA40F26E27C1`

## Preserved inputs

| Input | Result |
| --- | ---: |
| Baseline evidence | 87 files / 12,890,334 bytes |
| UI delta evidence | 5 files / 39,817 bytes |
| Required baseline families | Pass |
| Required delta files | Pass |
| Delta validation | Pass |
| Merge simulation conflicts | 0 |

Input database hashes recorded by the preflight:

- Preserved clone: `1BBAAB2ABDD0C51481747E5956098E61F67DA1CD603BB735A48D704A56C42C62`
- Validated delta: `AA9F40F7C0EE2701D49732C28454148598E4D5514DA5176CAA487A54EB34CCC7`
- Merge simulation: `E9D8E349DC79DD6AD966E63731775C5BD139D0988450362C9FB887D44B7336AD`

The tool hashes these inputs both before and after preflight and refuses output if any input changes.

## Cutover capture families

The manifest defines a repeatable capture checklist for:

1. Product, customer, supplier and configuration masters.
2. Purchases, payments, returns and purchase-return details.
3. Sales, POS, payments, returns, drafts, quotations and shipments.
4. All-location stock, transfers, transfer details and item traceability.
5. Payment accounts, cash flow, VAT, trial balance and profitability evidence.
6. Users, roles, permissions, business settings and CRM configuration.
7. Complete HRM capture for employees, departments, designations, attendance, shifts, holidays and leave controls; payroll remains excluded.
8. Uploaded purchase, sales and contact documents where a hosting backup can expose them.

## Gates

| Gate | Status |
| --- | --- |
| Required baseline evidence | Pass |
| Required delta evidence | Pass |
| Validated delta | Pass |
| Zero-conflict merge simulation | Pass |
| Transaction-free source window | Blocked |
| Fresh full exports from one cutoff | Blocked |
| Uploaded-file backup | Blocked |
| Atomic source backup | Blocked/unavailable |

The final two capture strategies are:

- Preferred: hosting-provider database plus uploaded-file backup.
- Maximum browser-only alternative: stop all source transactions, export every browser-accessible family into one timestamped directory, checksum immediately, repeat control totals, and obtain uploaded files separately where possible.

## Safety

- `merge_allowed=false`
- `posting_enabled=false`
- Source and clone mutation flags are false.
- Existing outputs cannot be overwritten.
- Full automated suite: 65 passed, 1 PostgreSQL-environment test skipped.
- PostgreSQL validation remains read-only on port 18081.
- UAT port 18082 remains disabled.

No real merge is authorized by this checkpoint. A user-confirmed transaction-free window is required before starting the browser-only final capture.
