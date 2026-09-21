# Security and workflow checkpoint

## Result

The source user/role evidence and target enterprise security controls have been staged for snapshot `bizmodo-2026-09-08-browser`. This operation used only captured local evidence and did not connect to or modify BizModo.

| Security layer | Count | Active/enabled |
|---|---:|---:|
| Users | 16 | 0 authenticated |
| Roles | 7 | 0 assignable |
| Permissions | 214 | 0 grantable |
| Captured source grants | 312 | 0 target grants |
| User-role evidence links | 16 | 0 enabled assignments |
| User location scopes | 16 | 0 enabled scopes |
| Approval-step role candidates | 9 | 0 enabled bindings |
| Segregation-of-duties rules | 5 | 0 enforced |
| Security policies | 3 | 0 enforced |
| Security activation gates | 8 | 0 activated |

Six roles have captured permission matrices. The Admin role is referenced by source users but its permission matrix was not present in the accessible export, so it remains `review_required_missing_matrix`.

## Credentials and identity

- Usernames, display names, email addresses and observed role names are retained only in the confidential target database.
- No password, password hash, session token or authentication secret was available or copied.
- All 16 users are `disabled_pending_identity_and_scope_approval`.
- Every user requires identity verification, a new target password and applicable MFA enrollment before activation.
- Source action-column markup is ignored and cannot become an executable permission.

## Roles and permissions

- All 312 checked source permissions are preserved as evidence through `source_granted=true`.
- Every target assignment remains `target_granted=false`.
- The source matrix exposes 214 distinct permission codes.
- 202 operational permissions are `draft_disabled` pending least-privilege review.
- HRM permissions are mapped into governed operational roles; payroll permissions remain excluded and cannot be granted operationally.
- The captured HRM permissions were not checked in the six source matrices and require governed target-role assignment. Payroll permissions remain excluded.

## Location scope and approvals

The user export contains no deterministic business-location assignment. Each user therefore has one `deny_all_pending_assignment` scope with no location selected. Global or branch access has not been inferred from role names.

Nine approval steps have disabled role candidates for review:

- Data owner → Manager.
- Finance controller → Accounts.
- System administrator → Admin.
- Inventory controller → Stock Transfer Coordinator.

These are proposed role mappings only. No person has been appointed as an approver, and all bindings remain disabled.

## Enterprise controls

Five draft maker/checker rules cover supplier maintenance, purchasing, sales credits/returns, payment reconciliation and access administration. Three disabled draft policies record recommended authentication, session and audit-retention baselines; their proposed settings require business/security approval.

Seven gates remain blocked for identity verification, location scope, role review, the missing Admin matrix, approval bindings, segregation of duties and security-policy approval. The HRM/payroll-exclusion gate is validated but remains disabled with the rest of the target system.

## Verification

- Repeated `security` execution created zero records.
- Authenticated users: 0.
- Target permission grants: 0.
- Active location scopes: 0.
- Enforced segregation rules and policies: 0.
- Active security gates: 0.
- `python -m pytest -q` passes 37 tests, compilation succeeds, and the expanded reconciliation report includes every security table.

This checkpoint is not user-access approval. Business owners must approve role matrices, branch scopes, named approvers, segregation rules and security policy values before any target login can be enabled.
