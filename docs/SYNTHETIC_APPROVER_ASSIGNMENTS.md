# Synthetic approver assignment checkpoint

Date: 2026-09-09

## Decision

Because named business approvers are unavailable, four controlled synthetic identities have been assigned for UAT design and visualization only:

| Required function | Synthetic identity | Alias | Scope |
|---|---|---|---|
| Data owner | UAT Data Steward | `uat.data.steward` | MAIN |
| Finance controller | UAT Finance Controller | `uat.finance.controller` | MAIN |
| Inventory controller | UAT Inventory Controller | `uat.inventory.controller` | MAIN |
| System administrator | UAT Security Administrator | `uat.security.administrator` | MAIN |

## Safety state

- Assignment status is `draft_synthetic`.
- Real-user bindings are zero.
- Production authority is false.
- Assignment activation is false.
- Approval actions are false.
- There is no automatic approval or delegation.
- Business data and the source BizModo application are unchanged.

## Verification

- Authenticated technical UAT passed 72 checks with 0 failures.
- The browser rendered all nine approval steps with their synthetic assignee, MAIN scope, draft status, and disabled state.
- The application test suite passed 55 tests, with 1 PostgreSQL-only test skipped outside its isolated profile.

These aliases must be replaced with accountable named people before any production governance activation.
