# Packaging/docs area notes: inferences and departures

Files: scripts/build_{windows.ps1,macos.sh,linux.sh}, deploy/{docker-compose.yml,.env.example,README.md}, README.md, HUONG_DAN.md, .gitignore, STATUS.md.

## Inferences (spec silent)
- Docker image names and tags (`ghcr.io/teableio/teable:v1.10.0`, `postgres:15.4`, `redis:7.2.4`) are not verified against any registry or Teable's release list (no network use, no reference); each is marked `VERIFY tag` in the compose file and README.
- Teable environment variable names (`PRISMA_DATABASE_URL`, `BACKEND_CACHE_PROVIDER`, `BACKEND_CACHE_REDIS_URI`, `SECRET_KEY`, `PUBLIC_ORIGIN`) and the attachment path `/app/.assets` are from memory of Teable's compose guide, unverified.
- Build scripts bundle `t3desk/data`, `t3desk/ui` and `plugins` with `--add-data` and use `t3desk/__main__.py` as entry. Whether `platform.py`/plugin loader finds `plugins/` inside a frozen app (`sys._MEIPASS`) was not checked.
- `.gitignore` also ignores `*.spec`, `build/`, `dist/`, `audit.jsonl`, `plugin.log`.
- The Teable version line in README.md is a placeholder ("TO BE RECORDED"), because no instance was available.
- Backup script uses the compose-project volume prefix `deploy_` (folder name), which depends on how it is started.

## Departures
- Image tags are also pinned in compose rather than read from `.env`, as the spec says tags are pinned in the compose file.
- Build scripts were not executed (PyInstaller not installed, instructed not to install it).
