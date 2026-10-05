# Teable on the NAS

Teable Community with PostgreSQL and Redis. T3 Desk uses this instance as its only shared store.

## 1. Check the NAS first

Teable's own guide asks for Linux, at least **4 GB RAM, 2 CPU cores and 40 GB of free disk**.
Before starting, confirm the NAS meets all three and supports Docker Compose.

ARM caveat: some NAS models have ARM CPUs, and the images in `docker-compose.yml` may not have an
ARM build. Find the NAS model and CPU type (`uname -m`: `x86_64` is expected; `aarch64` needs
checking) and verify each image's supported platforms before starting.

## 2. Verify image tags

The tags in `docker-compose.yml` are marked `VERIFY tag`. They are pinned exact versions but have
**not** been checked against the registry or the Teable version you will run. Check
<https://help.teable.ai/en/deploy/docker>, edit the tags, and record the Teable version in the
top-level `README.md`. Do not use `latest`.

## 3. Start

```
cd deploy
cp .env.example .env      # edit: PUBLIC_ORIGIN (no trailing slash), SECRET_KEY, passwords
docker compose up -d
docker compose ps
```

Open `PUBLIC_ORIGIN` in a browser, create the admin account and a space, then create a personal
access token for each T3 Desk user (read, create and update records only). The person who runs
`t3desk bootstrap` needs a token that can create tables and fields.

## 4. Stop

```
docker compose stop        # keeps containers and data
docker compose down        # removes containers; named volumes (data) are kept
```

Never run `docker compose down -v`: it deletes the data volumes.

## 5. Upgrade

1. Take a backup (section 6) and run the restore test.
2. Read Teable's release notes for the target version.
3. Edit the Teable image tag in `docker-compose.yml` (exact version).
4. `docker compose pull && docker compose up -d`
5. Re-check `t3desk/teable_client.py` against the API reference of the new version and update the
   version recorded in `README.md`.

## 6. Nightly backup and restore test

Back up PostgreSQL to a NAS share (example `/volume1/backup/teable`; adjust). Run this nightly
from the NAS scheduler:

```
#!/bin/sh
set -eu
cd /path/to/deploy
. ./.env
DEST=/volume1/backup/teable
STAMP=$(date +%Y%m%d-%H%M)
docker compose exec -T teable-db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$DEST/teable-$STAMP.dump"
# Attachments live in the teable-data volume; copy it too. Volume name is prefixed by the
# compose project name (see `docker volume ls`).
docker run --rm -v deploy_teable-data:/data -v "$DEST":/backup alpine \
  tar czf "/backup/teable-data-$STAMP.tgz" -C /data .
# keep 14 days
find "$DEST" -name 'teable-*' -mtime +14 -delete
```

Restore test (after setting up the backup and after every upgrade; always into a scratch
database, never the live one):

```
docker compose exec -T teable-db createdb -U "$POSTGRES_USER" restore_test
docker compose exec -T teable-db pg_restore -U "$POSTGRES_USER" -d restore_test --no-owner < "$DEST/teable-<stamp>.dump"
docker compose exec -T teable-db psql -U "$POSTGRES_USER" -d restore_test -c "\dt"
docker compose exec -T teable-db dropdb -U "$POSTGRES_USER" restore_test
```

A backup counts only after a restore test has succeeded. These scripts are UNVERIFIED: they were
not run against a real NAS.

## 7. Notes

- `.env` holds secrets: keep it out of git and off shared folders.
- T3 Desk never deletes data in Teable. Do not delete tables, including the scratch table
  `zz_scratch_check` that `t3desk bootstrap` creates.
