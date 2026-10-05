# T3 Desk

Desktop app for TECOTEC Technologies' T3 design workflow. Engineers, sourcing and the PM enter
design data through forms; the app keeps drafts locally, commits them to a Teable base on the
office NAS with first-come ID ownership, and shows the decision tree on every screen. Outside
systems (Hermes, gbrain MCP, Paperclip TODO AI) are reached only through plugins.

Spec: `docs/REQUIREMENTS.md`. Project rules: `CLAUDE.md`. Running state: `STATUS.md`.

## Stack

Python 3.11+, `pywebview` window (or `--browser`), plain HTML/CSS/JS UI served from `127.0.0.1`,
`httpx`, standard-library `sqlite3`, `keyring`, `pyyaml`. Teable (Community) with PostgreSQL and
Redis on the NAS (`deploy/`). Packaging with PyInstaller (`scripts/`).

## Run from source

```
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: . .venv/bin/activate
pip install -e ".[dev]"
python -m t3desk                  # native window
python -m t3desk --browser        # same UI in the default browser
python -m t3desk bootstrap --help # create tables and fields in a Teable base
python scripts/smoke.py           # start, load one screen, exit
```

Optional: `pip install -e ".[mcp]"` for the gbrain MCP plugin.

## Tests

```
pytest -q
```

All tests run against `tests/fake_teable.py` and `tests/fake_hermes.py`, with no network. Note:
`tests/test_plugins.py` is slow (about a minute) because it starts many fake servers.

## Teable

Teable server version used: **TO BE RECORDED** (fill in the version actually deployed on the NAS
here, after checking every path and payload in `t3desk/teable_client.py` against that version's API
reference). The compose file in `deploy/` pins image tags that are marked "verify".

Setup, backup and upgrade: `deploy/README.md`. Each user uses their own Teable token.

## Known limitation: stale writes

Teable's update-record call has no version or if-match option. Before sending a change, T3 Desk
re-reads the record and compares `lastModifiedTime`; if it differs, the user sees both versions
and chooses per field. A second write landing between that re-read and the update can still be
lost. The app cannot close that window.

## UNVERIFIED

Nothing here has been run against the real systems.

- **Teable**: the client, bootstrap and fake server share the same assumptions (table create
  payload, `unique`/`notNull` in field create, filter shape, duplicate-ID error status and text,
  `createdBy` shape). Passing tests do not prove them.
- **Hermes** adapter (`plugins/hermes_skill`): wire format is invented; no reference was supplied.
- **gbrain** adapter (`plugins/mcp_tool`): tool mappings are guesses; tested only with a fake session.
- **Paperclip TODO AI** push (`plugins/task_outbox`): endpoint is invented; only the `cong_viec`
  table contract is tested.
- **Packaging**: the build scripts have not been run; PyInstaller is not installed in the venv.
  macOS and Linux were never run.
- **pywebview window** on any OS, and Ctrl/Cmd+S there.

## Layout

```
t3desk/    app package        plugins/   hermes_skill, mcp_tool, task_outbox
deploy/    Teable compose     scripts/   build_*.ps1/.sh, smoke.py
tests/     fakes and tests    docs/      REQUIREMENTS.md, reference/, notes/
```
