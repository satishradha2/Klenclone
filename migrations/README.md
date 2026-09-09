# Database migrations

The baseline migration creates the full schema on a new empty database. Set `KLEN_DATABASE_URL` and run `alembic upgrade head`.

Do not run the baseline against the populated legacy local SQLite database unless it has first been stamped after schema verification. Destructive downgrade is intentionally disabled because the database contains migration evidence.
