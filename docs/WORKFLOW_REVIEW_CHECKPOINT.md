# Workflow review checkpoint

Date: 2026-09-09

## Available blueprints

| Workflow | Initial state | States | Transitions | Runtime state |
|---|---|---:|---:|---|
| Migration exception resolution | Open | 4 | 3 | Draft locked |
| Journal blueprint activation | Draft | 4 | 3 | Draft locked |
| Migration batch activation | Draft | 5 | 4 | Draft locked |
| Opening balance approval | Pending | 3 | 2 | Draft locked |

Four approval policies are also preserved: reconciliation exception resolution, inventory opening approval, journal blueprint activation, and migration batch activation. No monetary threshold was inferred from the source.

## UAT exposure

The authenticated UAT workspace now includes a protected **Workflows** tab. It exposes only workflow names, initial state, state/transition counts, review status, and the disabled execution flag. There is no endpoint for submitting, approving, rejecting, activating, posting, or reserving numbers.

## Activation blockers

- Approver roles and user bindings require business approval.
- Approval thresholds and delegation rules require explicit definitions.
- The 188 migration discrepancies must retain evidence and resolution decisions.
- Identity and location assignments for real users remain unprovisioned.
- Financial posting, operational workflows, and source write-back remain disabled.
- Final cutover still requires a transaction-free source window or hosting-level atomic backup.

The next permitted action is business-owner review of the workflow states, approver roles, thresholds, and discrepancy decisions. Activation is not authorized by this checkpoint.
