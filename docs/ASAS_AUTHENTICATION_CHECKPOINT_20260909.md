# Asas ERP authentication checkpoint

Date: 2026-09-09

## Outcome

The independent Asas ERP preview now requires authentication. A new Asas-only
administrator identity was provisioned; no copied BizModo identity or password
was enabled or reused.

- Login route: `http://127.0.0.1:18082/login`
- Provisioned login name: `asas-admin`
- Role: `operations_administrator`
- Permissions: `clone.read`, `migration.review`, `sales.draft.create`,
  `purchase.draft.create`
- Session lifetime: 30 minutes
- Cookie: HTTP-only, SameSite Strict
- Logout: CSRF-protected
- Login throttling: five attempts per five-minute window
- Posting permission: absent
- HRM access at this historical checkpoint: absent; the current target ERP now
  includes separately authorized HRM roles and workflows. Payroll remains excluded.

The password is stored only as a PBKDF2-SHA256 hash with 600,000 iterations in
the ignored local environment file `.env.asas.local`. The plaintext password is
not written to the application source, database, documentation, or audit log.

## Enforcement

- Unauthenticated business API requests return HTTP 401.
- Anonymous access to `/` redirects to the Asas-branded login page.
- Health and session-discovery endpoints remain available without a session.
- Only login and CSRF-validated logout POST requests are accepted.
- All business-data mutation methods remain rejected.
- Login success, denial, rate limiting and logout are append-only audit events in
  the independent clone database.
- Existing source-derived users remain `disabled_unprovisioned` and require
  separate identity verification and new passwords before future activation.

## Verification

- Anonymous overview request: HTTP 401
- Provisioned administrator login: passed
- Authenticated overview and provisional delta registers: passed
- Browser login and dashboard rendering: passed
- CSRF logout enforcement: passed
- Role payload confirms `posting_enabled=false`
- Container health: passed
- Full automated suite: 84 passed, 1 skipped

## Remaining security gates

1. Identify actual Asas users and approve their new ERP role and location scope.
2. Provision each user with a new credential; never copy BizModo passwords.
3. Add persistent multi-instance session storage before production deployment.
4. Require HTTPS and secure cookies outside loopback development.
5. Add MFA for administrators and privileged financial roles.
6. Complete role-specific authorization tests before enabling any operational
   creation, approval or posting endpoint.
