# PostgreSQL backup and restore

`postgres-backup.sh` creates a custom-format logical backup using the running PostgreSQL 18 container. `verify-postgres-restore.sh` now reads the source without inserting probe data, creates a uniquely named isolated database, restores the dump, compares object checksums and history schema, and removes only that temporary database and dump. It never reuses or drops an existing restore database.

Local logical backup is the first recovery path; it does not replace production WAL archiving and PITR. Production RPO/RTO, archive storage, encryption, retention, off-host copies and quarterly restore drills must be defined with the school operations team.

Run from the repository root:

```bash
infra/backup/postgres-backup.sh
infra/backup/verify-postgres-restore.sh
```

Backups are written under `backups/` by default and are excluded from version control. Backup files may contain sensitive and licensed data and must not be copied to an unapproved location.

## Retention boundary

Do not automatically purge database history or PDF versions. Fulltext bucket versioning must remain enabled; any object/version expiration requires an explicit governance decision. Run `apps/platform-api/scripts/verify_fulltext_retention.py` inside the configured API environment to check this without modifying files. A checksum is not a backup, bucket versioning is not off-host replication, and previously deleted versions cannot be reconstructed from audit rows. This upgrade does not install a recurring backup schedule or choose an off-host storage destination.
