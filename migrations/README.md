# Database migrations

The baseline migration creates the full schema on a new empty database. Set `KLEN_DATABASE_URL` and run `alembic upgrade head`.

Do not run the baseline against the populated legacy local SQLite database unless it has first been stamped after schema verification. Destructive downgrade is intentionally disabled because the database contains migration evidence.

## Separate operational PostgreSQL database

The ERP operational database is distinct from the preserved clone database above. Its legacy schema through revision `0061` was installed by the operational initializer. Production web startup now performs a read-only schema-contract check for revision `0067` and will refuse an unmigrated or drifted operational database; it does not run schema DDL.

Run the operational upgrade as a separate maintenance action with `ASAS_OPERATIONAL_DATABASE_URL` set to the **target operational PostgreSQL database**, not BizModo or the clone. For an existing database, first take and restore-test a custom-format `pg_dump -Fc` archive, then run:

```text
python -m klen_clone.operational_migrate --backup-file /path/to/verified-backup.dump
python -m klen_clone.operational_migrate --verify-only
```

The command records the backup archive SHA-256, installs/checks the `0067` contract, and is idempotent on a database already at that revision. A new empty operational database does not require a prior backup. The `0062` revision was the checked baseline around the legacy initializer; `0063` adds target-invoice provenance to sales returns; `0064` adds nullable dispatch valuation snapshots; `0065` expands customer-invoice and integrated-posting status/resource constraints for delivery-backed invoice posting; `0066` adds governed customer-refund payout records and bank-statement linkage; `0067` adds no-stock customer pricing credits, compensating refund receipts, and their bank-statement links. Historical dispatch rows remain unvalued and must be reconciled from genuine evidence before accounting posting—no cost is inferred from today's average. These are not reconstructions of historical upgrade scripts; every subsequent schema change requires a new explicit revision and its own rehearsal before production startup.
