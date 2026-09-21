# Users, Roles and Approval Matrix Checkpoint — 2026-09-15

## Delivered scope

The independent Asas ERP now has a database-backed access-administration workspace. It manages target-ERP access profiles and role assignments only; it never edits BizModo identities, permissions, settings or evidence.

- 30 enterprise roles across administration, finance, purchasing, inventory, logistics, sales, van operations, executive access and audit.
- Multiple roles per user.
- Company, branch, warehouse and van scope.
- Effective-from and optional effective-to dates.
- Optional AED approval limits restricted to approving roles.
- MFA-required marking for sensitive roles.
- Active, suspended, inactive and pending-provisioning access-profile states.
- Immutable operational audit events for user creation, status changes, role assignment and revocation.

## Authentication boundary

Passwords and password hashes are not stored in the access-control tables. Authentication remains independently provisioned through the protected Asas identity file. A profile whose login is not independently provisioned remains `pending_provisioning` and cannot be activated through the ERP screen.

Existing `operations_administrator` identities receive an audited target-ERP `administrator` compatibility assignment. This grants company/access administration without widening their existing transaction-location scope.

## Segregation and scope controls

- One user cannot hold Finance Maker and Finance Approver assignments where company, operating-unit scope and effective dates overlap.
- Duplicate scoped assignments are rejected.
- Unknown companies, branches, warehouses and vans are rejected.
- Warehouse and van scopes must belong to the selected branch.
- Users cannot suspend/deactivate themselves or revoke their own access-administration assignment.
- Suspending an access profile blocks authentication even when valid credentials still exist.
- Effective role permissions are resolved from PostgreSQL for each authenticated request and combined with the independently provisioned baseline permissions.

## User interface and API

The **Users & roles** workspace is available at `#users-roles` to authorised access administrators and reviewers.

- `GET /api/v1/access-control`
- `POST /api/v1/access-control/users`
- `PATCH /api/v1/access-control/users/{user_key}/status`
- `POST /api/v1/access-control/users/{user_key}/assignments`
- `DELETE /api/v1/access-control/users/{user_key}/assignments/{assignment_id}`

All mutations require authentication, CSRF validation and an access-administration permission. The screen labels identity-provisioning readiness and never displays credentials.

## Safety state

BizModo source access remains strictly read-only. Posting and production activation controls are unchanged and remain disabled unless their separate gates are satisfied.
