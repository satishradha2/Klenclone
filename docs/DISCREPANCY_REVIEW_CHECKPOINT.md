# Protected discrepancy review checkpoint

Date: 2026-09-09

## Outcome

The authenticated UAT workspace now exposes all 188 migration discrepancies as protected row-level records. Reviewers can filter/search the queue, inspect redacted evidence, and add target-side draft resolution proposals.

## Data separation

- Cloned business and exception data remain in `var/klen_uat_validation.db`.
- Review proposals and review events are stored separately in `var/klen_uat_reviews.db`.
- The sidecar database contains no copied passwords and no BizModo source payloads.
- Every proposal stores a SHA-256 fingerprint of the unchanged exception record.
- Database triggers prohibit updating or deleting proposals and review events.
- Proposals are versioned; a changed opinion creates a new version rather than replacing history.

## Authorization boundary

- The discrepancy list and proposal endpoint require an authenticated synthetic UAT principal with the review permission.
- Proposal submission requires the active session CSRF token.
- Resolution types are restricted to an explicit allowlist.
- Rationale and proposed target value sizes are limited.
- Every saved proposal remains `draft`; no approval or source correction is performed.
- ERP create/edit/delete/post/approve/activate endpoints remain unavailable.

## Validation evidence

- Automated authenticated UAT: 47 passed, 0 failed.
- Application test suite: 54 passed, 1 PostgreSQL-only test skipped outside its isolated profile.
- Browser verification rendered 188 protected discrepancies and successfully created one append-only UAT draft for exception `#170`.
- The draft uses `no_change_retain_block`; the exception remains open and blocked.
- The exception `#170` row was compared between the original clone and UAT clone and remained identical.
- Sidecar counts after verification: 1 proposal and 1 corresponding audit event.

## Next gate

Business owners must review proposed resolutions and provide explicit approvals. The current build deliberately has no approval action. An approval workflow can be enabled only after approver roles, delegation, thresholds, and segregation-of-duties rules are confirmed.
