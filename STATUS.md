# STATUS

Merged from `docs/notes/*.md` (commit, foundation, packaging, plugins, rules, ui). Test results are not recorded here; run `pytest -q` and report the real output.

## Done

- Foundation: `pyproject.toml`, `t3desk/{schema,teable_client,bootstrap,main}.py`, `schema.yaml`, `labels_vi.yaml`, `tests/fake_teable.py`; bootstrap with scratch-table duplicate check.
- Commit: `store.py`, `validation.py`, `commit.py` (conflict with new ID, stale-edit per-field resolution, offline refusal, secrets in keyring or 0600 file).
- Rules: `rules.py`, `decision_tree.py`, `decision_tree.yaml`, pressure-tank fixture, tests.
- UI: `server.py`, `main.py`, `platform.py`, `ui/*`, `labels_ui_vi.yaml`, `tests/test_server.py`, `scripts/smoke.py`. Localhost-only server with per-run session header and CSP.
- Plugins: `plugins_api.py`, `rfq.py`, `plugins/{hermes_skill,mcp_tool,task_outbox}`, `tests/fake_hermes.py`, `tests/test_plugins.py` (about 65 s).
- Packaging/docs: build scripts for Windows, macOS, Linux; `deploy/` (compose, `.env.example`, README); `README.md`; `HUONG_DAN.md`; `.gitignore`.

## Next

- Plugins have no UI wiring (Settings page, buttons, preview dialog); the caller must call `host.start()`, `host.after_commit(report)`, `host.poll_jobs()` and supply the confirm hook.
- Test 15 (socket patching, whole app) is not in the plugins area.
- Record the deployed Teable version in README.md; verify image tags in `deploy/docker-compose.yml`.
- Check that the plugin loader finds `plugins/` inside a frozen PyInstaller app.
- Run the build scripts on each OS (PyInstaller is not installed in the venv).

## Unverified

- Teable (no real instance): all paths and payloads in `teable_client.py` (table create with `fields` and `records: []`, `unique`/`notNull` in table-create fields, number/date `options.formatting`, `GET /api/base/{id}/table`, `GET /api/auth/user`, `POST /api/base` with `spaceId`, filter shape, `createdBy` shape, `createdTime`/`autoNumber` on create responses, `get_record` returning `lastModifiedTime`, unique-violation as HTTP 400 or 409 and its message text). The fake mirrors these assumptions.
- Hermes adapter: wire format invented (`POST /v1/skills/{skill}/runs`, `GET /v1/runs/{ref}`); skill names `rfq` / `rfp` are placeholders. UNVERIFIED in code and README.
- gbrain MCP adapter: tool mappings are guesses; real `mcp` stdio/URL path never run. UNVERIFIED.
- Paperclip push (`POST <url>/api/tasks`): invented; only the `cong_viec` contract is tested. UNVERIFIED.
- Docker image tags and Teable environment variable names in `deploy/`; backup and restore scripts never run on a NAS.
- Packaging on all three OSes; pywebview window on any OS; macOS and Linux never run; Ctrl or Cmd + S in pywebview; blob CSV download in some pywebview back ends.
- UI walk in headless Edge on Windows was a scratch script, not part of the repo tests.

## Departures

- Withdrawal on read-back duplicate: the app retires its own record by status (`Hủy` / `Loại`) instead of deleting (rule 1). Tables without such a status cannot be retired; the message asks for a manual fix.
- Scratch table `zz_scratch_check` stays in the base, so a bootstrapped base holds 15 tables (pass `scratch_check=False` to skip).
- Drafts are overlaid on cached tables before rules run (spec says rules read cached tables).
- Plugin buttons on screens are not in the UI; the tree panel has no draft marker; `Cây hệ thống` has no drag or inline edit.
- Several areas wrote tests together with code rather than strictly test-first (commit, UI).
- Section 12 test 4 is covered at client level (foundation) and commit level (commit); the commit module must call `ensure_unique_flags`.
- Image tags are pinned in the compose file; build scripts were not executed.
- Extra module `t3desk/schema.py` is not in the section 12 layout.

## Questions

Inputs the spec (section 13) lists as needed from Viet; adapters are built against fakes until answered:

- Teable: NAS address, version, whether already running; NAS model and CPU type (ARM images).
- Hermes: API reference for running a skill, authentication, skill names for RFQ and RFP, where generated documents are stored.
- gbrain: how to reach the MCP server (command or URL) and which tools to offer.
- Paperclip TODO AI: pull from `cong_viec` or push; for push the endpoint, authentication and task fields.
- Data leaving the LAN: may RFQ and RFP payloads for defence projects go to Hermes, or is a per-project switch needed to block all plugin sends?
- Spec gaps inferred (see notes): `doi_chieu` extra fields, choice sets for `mua_hang`, `moc`, `sai_lech`, `cong_viec` status, placeholder exchange rates and scoring weights; confirm or correct.
