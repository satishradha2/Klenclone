# PostgreSQL Validation Checkpoint

Validation date: 2026-09-09  
Compose project: `klen-validation`  
Snapshot: `synthetic-postgres-validation`  
Data classification: synthetic only.

## Outcome

The versioned schema, authentication dependencies, RBAC checks, location filtering, HTTP read-only controls, service restart behavior and PostgreSQL backup/restore path passed in an isolated Docker environment. No source export, browser session, local clone database or real business row was mounted or copied into the validation stack.

## Automated checks

- Local suite: 47 passed; the environment-gated PostgreSQL test was skipped as designed.
- PostgreSQL integration suite: 1 passed.
- Alembic revision: `20260908_0001` on PostgreSQL 17.
- Missing bearer token: HTTP 401.
- Active principal without location scope: HTTP 403.
- Active principal with `sell.view` and one location: one permitted document returned; the second location was excluded.
- Revoked target permission: HTTP 403.
- Mutating request: HTTP 405.
- Authentication and posting in the containerized control center: disabled.

## Container and recovery checks

- Database stayed inside the private Docker network; PostgreSQL port 5432 was not published.
- Control center was bound to `127.0.0.1:18080` during validation.
- Health check reached `healthy` before and after a controlled service restart.
- API health remained `ok` and the synthetic snapshot remained available after restart.
- Browser rendering showed only `Synthetic Validation Company`, 3 synthetic raw records and 2 synthetic documents.
- Browser warning/error log was empty.

## Backup and restore reconciliation

A custom-format `pg_dump` was restored into the explicitly named temporary database `klen_restore_validation`. Original and restored values matched exactly:

| Control | Original | Restored |
|---|---:|---:|
| Alembic revision | 20260908_0001 | 20260908_0001 |
| Snapshots | 1 | 1 |
| Raw records | 3 | 3 |
| Transaction documents | 2 | 2 |
| Authentication principals | 1 | 1 |
| Locations | 2 | 2 |

The restored database and temporary dump were deleted after reconciliation.

## Defects found and corrected

1. The non-root container could not create its local SQLite fallback directory. The image now creates `/app/var` with ownership assigned to the `klen` user; rebuild and import smoke test passed.
2. The overview hard-coded the real organization name, causing it to appear in a synthetic environment. The organization label now comes from the selected snapshot with a neutral fallback.
3. Health and summary metadata hard-coded authentication as false. They now report the validated runtime setting; the deployed assurance profile still sets it to false.
4. Pytest attempted to write its cache in the read-only test container. The integration command now disables that cache provider.

## Cleanup evidence

The `klen-validation` control-center container, PostgreSQL container, private network and named PostgreSQL volume were removed with `docker compose down -v`. Verification returned zero remaining validation containers and zero validation volumes. These deleted resources contained synthetic data only and were intentionally non-recoverable.

## Remaining gate

This proves the empty-schema and synthetic-runtime path, not the real-data migration. Before any operational activation, the 41,444-row cloned dataset must be copied into a separate PostgreSQL environment and reconciled by entity counts, source keys, hashes, document relationships, inventory quantities, financial balances and exception states. Authentication should remain disabled during that copy.
