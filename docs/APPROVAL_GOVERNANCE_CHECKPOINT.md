# Draft approval governance checkpoint

Date: 2026-09-09

## Outcome

Protected UAT views now expose nine approval steps and five segregation-of-duties controls. Four distinct synthetic draft identities cover the required functions. They are design evidence only: no real user is assigned, no production authority exists, and no approval action is enabled.

## Proposed approval mappings

| Policy | Step | Required function | Proposed source role | Enabled |
|---|---:|---|---|---|
| Exception resolution | 1 | Data owner | Manager | No |
| Exception resolution | 2 | Finance controller | Accounts | No |
| Inventory opening | 1 | Inventory controller | Stock Transfer Coordinator | No |
| Inventory opening | 2 | Finance controller | Accounts | No |
| Journal activation | 1 | Finance controller | Accounts | No |
| Journal activation | 2 | System administrator | Admin | No |
| Migration batch activation | 1 | Data owner | Manager | No |
| Migration batch activation | 2 | Finance controller | Accounts | No |
| Migration batch activation | 3 | System administrator | Admin | No |

These mappings are inferred proposals, not approved assignments. For controlled UAT, the functions are mapped to `UAT Data Steward`, `UAT Finance Controller`, `UAT Inventory Controller`, and `UAT Security Administrator`. Every alias is restricted to `MAIN`, marked `draft_synthetic`, and has no production authority.

## Draft segregation controls

- Supplier maker versus supplier approver
- Purchase maker versus purchase approver/poster
- Sale/return maker versus credit approver/poster
- Payment creator versus bank reconciler
- Access administrator versus access approver

Every control remains `draft_pending_approval` with enforcement disabled.

## Validation

- Automated authenticated UAT: 72 passed, 0 failed.
- Application suite: 55 passed, 1 PostgreSQL-only test skipped outside its isolated profile.
- Browser verification rendered all nine disabled approval steps with the four synthetic assignees and all five disabled segregation controls.
- No API exists to enable bindings, approve a request, enforce a rule, delegate authority, or post a transaction.

## Required decisions

Before production activation, replace every synthetic alias with an accountable named person, approve the allowed locations and monetary thresholds, define absence/delegation rules, and confirm that no maker is also their own checker. Until then, every workflow and permission assignment remains disabled.
