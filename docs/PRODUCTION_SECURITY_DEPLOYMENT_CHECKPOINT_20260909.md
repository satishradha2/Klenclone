# Production Security and Deployment Checkpoint — 2026-09-09

## Outcome

The application now contains a fail-closed production security profile and a production Compose overlay. The local ERP preview was rebuilt with these controls while remaining in non-production, non-posting mode. No public production deployment has been performed.

## Security controls implemented

- Production startup refuses disabled authentication, non-PostgreSQL operational storage, weak session secrets, wildcard or missing allowed hosts, and incomplete posting approval.
- Production sessions are opaque, database-backed, revocable, expiry-controlled, and reusable across multiple application workers. Only session-token hashes are stored; CSRF values are derived with HMAC.
- Login throttling is shared through the operational database and stores a keyed hash instead of the submitted username/client combination.
- Production cookies use the `__Host-` prefix with Secure, HttpOnly, SameSite Strict and root-path constraints.
- State-changing operations retain CSRF and permission checks with constant-time token comparison.
- Host validation, HTTPS enforcement behind explicitly trusted proxies, HSTS, CSP, frame denial, restrictive permissions policy, no-store caching and request correlation identifiers are enabled.
- Request bodies above 2 MiB are rejected before route processing.
- Authentication audits use the operational audit ledger in production so the preserved clone is not mutated by sign-in activity.
- Posting endpoints are admitted by the operational-write safety layer only after route-level posting activation, permission, scope and document controls are satisfied.
- Posting activation requires `ASAS_POSTING_ENABLED=true`, `ASAS_POSTING_ACTIVATION_CONFIRMED=true`, and a non-trivial approval reference in production.

## Deployment controls

- `compose.production.yaml` clears workstation environment files, bind mounts, published ports and local database dependencies from the ERP service.
- Clone and operational PostgreSQL connections, session secrets, allowed hosts, proxy trust and identity-secret location are mandatory deployment inputs.
- The service remains read-only at the container filesystem level, drops Linux capabilities, blocks privilege escalation, limits processes/file descriptors and exposes only the internal application port.
- TLS termination must be provided by the approved reverse proxy or ingress. Its exact network address must be supplied through `ASAS_TRUSTED_PROXY_IPS`; broad trust is not permitted.

## Activation sequence

1. Provision separate production clone and operational PostgreSQL databases.
2. Restore and checksum-verify the approved clone backup; do not point the service at live BizModo.
3. Store the identity JSON, database credentials and session secret in the deployment secret manager.
4. Configure TLS, DNS, explicit allowed hosts and the exact reverse-proxy addresses.
5. Validate the merged Compose configuration and image digest, then deploy with posting disabled.
6. Verify health, authenticated readiness, backup/restore, audit persistence, session revocation and monitoring alerts.
7. Complete the final BizModo capture and full reconciliation.
8. Record named approval and a rollback point. Only then set all three posting-activation controls and redeploy.

## Rollback

- Disable posting first and retain the operational database unchanged.
- Route traffic to the previous immutable image.
- Do not restore an older operational database over newer posted transactions. Database restoration requires an incident decision and reconciliation of every posting batch created after the backup.

## Current status

Production deployment is intentionally pending because no production host, TLS endpoint, managed-secret location, monitoring destination or final cutover approval has been supplied. Local posting remains disabled and HR/payroll remains excluded.

Verification completed with 130 passing tests and one optional PostgreSQL integration test skipped. The production Compose overlay validates successfully with synthetic configuration. The rebuilt local Docker deployment is healthy on port 18082, operational schema version 0015 is installed, and the preserved counts remain 464 products, 881 parties, 579 stock positions and 264 opening party balances. All integrated posting ledgers remain empty.
