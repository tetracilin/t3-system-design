# STATUS

Merged from `docs/notes/*.md` (commit, foundation, packaging, plugins, rules, ui). Test results are not recorded here; run the suite and report the real output. Last known (7 Oct 2026): 462 passed, 1 failed (a wrong assertion in a new decision-tree test, fixed and re-run alone: 24 passed); the whole suite was not re-run after that fix, run it first.

Run the tests: `.\.venv\Scripts\python.exe -m pytest -o addopts="" -p no:cacheprovider` (about 6 minutes), `.\.venv\Scripts\python.exe scripts\smoke.py`. Run the app: `run.bat --browser` (uses the project .venv; without `--browser` it opens the native window).

## Done

- Foundation: `pyproject.toml`, `t3desk/{schema,teable_client,bootstrap,main}.py`, `schema.yaml`, `labels_vi.yaml`, `tests/fake_teable.py`; bootstrap with scratch-table duplicate check.
- Commit: `store.py`, `validation.py`, `commit.py` (conflict with new ID, stale-edit per-field resolution, offline refusal, secrets in keyring or 0600 file).
- Rules: `rules.py`, `decision_tree.py`, `decision_tree.yaml`, pressure-tank fixture, tests.
- UI: `server.py`, `main.py`, `platform.py`, `ui/*`, `labels_ui_vi.yaml`, `tests/test_server.py`, `scripts/smoke.py`. Localhost-only server with per-run session header and CSP.
- Plugins: `plugins_api.py`, `rfq.py`, `plugins/{hermes_skill,mcp_tool,task_outbox}`, `tests/fake_hermes.py`, `tests/test_plugins.py` (about 65 s).
- Packaging/docs: build scripts for Windows, macOS, Linux; `deploy/` (compose, `.env.example`, README); `README.md`; `HUONG_DAN.md`; `.gitignore`.
- Predator user-flow test (8 Oct 2026): `tests/test_flow_predator.py` drives the whole design flow through the `/api/*` routes the UI uses (requirements, three architectures, choose before and after commit, gates, tree, allocation, specs, candidates, checks, sourcing, commit order, two-user conflict, offline, RFQs through fake Hermes, KT-A chosen and KT-B/C rejected, task_outbox). Findings: `docs/notes/flow-predator.md`.
- Fixes from that flow: next-ID proposal for the root and its children (`N0`, `N1`, never `N0.1`); new optional `nut.ma_kt` field, nodes of a rejected architecture (and their descendants) are not active leaves (`rules.py` `_inactive_nodes`); `/api/*` screens return a `names` map and the UI shows `code - name` in pickers, tables, matrix headers and filters; the form overlay stops at the decision tree panel; `decision_tree.yaml` has `help` per question and a `guide:` glossary shown under the tree (`drawHelp` in `app.js`).
- Design work only, NOT coded: `docs/UI-V2-SPEC.md` (4-pane inline-edit UI, Markdown notes, Hermes placeholder, keyboard model), mockup `docs/mockups/workspace-4-pane.{html,png}`.

## Next

- **Decided 8 Oct 2026 (office hours, `docs/designs/review-first-pilot.md`, APPROVED):** UI v2 is frozen. Build the
  weekly review view, findings stored in `sai_lech`, "my open findings" on Tổng quan, two new warnings plus the existing
  `tree_too_early` shown on forms; then pilot v1 with one named junior on a real project. The UI v2 questions below are
  no longer blocking.
- **Viet to fill in:** pilot junior: ___ · project: ___ · reviewer: ___ · session 1 date: ___

- Waiting on Viet before coding UI v2: answer the questions in `docs/UI-V2-SPEC.md` section 11 (four-pane layout replaces requirements section 8; inline edit vs the architecture-choice dialog; new table `ghi_chu` = 15 tables and a change to acceptance test 1; Markdown renderer; Hermes placeholder; whether pane 4 is context + notes + Hermes; all screens or only system design and node). Then write the acceptance tests of spec section 10 first.
- Electron, Hyprland and Quickshell were requested but conflict with CLAUDE.md (stack fixed), requirements section 3 (Electron rejected), the 80 MB / 200 MB limits and Windows/macOS/Ubuntu support (Hyprland and Quickshell are Linux-only). Not started; needs an explicit decision.
- Existing Teable bases need `t3desk bootstrap` run again to add the new `nut.ma_kt` column.
- Decide: two chosen architectures give no warning (section 7 silent); nodes have no status to retire them; any role may set an architecture to `Loại`.
- Plugins have no UI wiring (Settings page, buttons, preview dialog); the caller must call `host.start()`, `host.after_commit(report)`, `host.poll_jobs()` and supply the confirm hook.
- Test 15 (socket patching, whole app) is not in the plugins area.
- Record the deployed Teable version in README.md; verify image tags in `deploy/docker-compose.yml`.
- Check that the plugin loader finds `plugins/` inside a frozen PyInstaller app.
- Run the build scripts on each OS (PyInstaller is not installed in the venv).

## Unverified

- Teable: verified against release.2026-08-19T02-25-59Z.2698 on 5 Oct 2026 (see `docs/notes/teable-live.md`); still unverified there: two different real users, more than 1000 rows, limited-permission tokens, rate limits, non-UTC date fields.
- Hermes adapter: follows the documented Runs API (`POST /v1/runs`, `GET /v1/runs/{id}`, Idempotency-Key; see `docs/reference/hermes-api-server.md`) but never run against a real Hermes. UNVERIFIED: run `status` values, where documents are stored, real skill names (`rfq` / `rfp` are placeholders), whether the skill obeys the JSON-reply instruction.
- gbrain MCP adapter: remote HTTP MCP (`https://<host>/mcp`, bearer token; see `docs/reference/gbrain-mcp.md`), read-only (write tools blocked in code). Never run against a real gbrain. UNVERIFIED: `search`/`query` argument names and response shapes. The guessed RFQ/RFP mapping was removed.
- Paperclip push (`POST <url>/api/tasks`): invented; only the `cong_viec` contract is tested. UNVERIFIED. Paperclip's MCP page and the webhooks plugin (outbound events only) do not give an inbound task API; waiting for Paperclip's HTTP API docs.
- Docker image tags and Teable environment variable names in `deploy/`; backup and restore scripts never run on a NAS.
- Packaging on all three OSes; pywebview window on any OS; macOS and Linux never run; Ctrl or Cmd + S in pywebview; blob CSV download in some pywebview back ends.
- UI walk in headless Edge on Windows was a scratch script, not part of the repo tests.

## Departures

- New field `nut.ma_kt` (ref `kien_truc`) and the rule that its rejected architecture deactivates the node: not in requirements section 4 or 7. Added on the user's instruction after the predator flow; needs approval.
- `decision_tree.yaml` carries extra keys (`help`, top-level `guide`) beyond section 6; the loader ignores `guide` as a tree.
- `/api/*` payloads carry `names` and the trees payload carries `guide`: UI data only.
- Withdrawal on read-back duplicate: the app retires its own record by status (`Hủy` / `Loại`) instead of deleting (rule 1). Tables without such a status cannot be retired; the message asks for a manual fix.
- Scratch table `zz_scratch_check` stays in the base, so a bootstrapped base holds 15 tables (pass `scratch_check=False` to skip).
- Drafts are overlaid on cached tables before rules run (spec says rules read cached tables).
- Plugin buttons on screens are not in the UI; the tree panel has no draft marker; `Cây hệ thống` has no drag or inline edit.
- Several areas wrote tests together with code rather than strictly test-first (commit, UI).
- Section 12 test 4 is covered at client level (foundation) and commit level (commit); the commit module must call `ensure_unique_flags`.
- Image tags are pinned in the compose file; build scripts were not executed.
- Exchange-rate unit change (6 Oct 2026): rates are now VND per ONE unit (`vnd_per_usd` 25000, `vnd_per_eur` 27000; VND built in as 1) under NEW keys; costs stay in million VND. The old `ty_gia_<CUR>` rows (million VND per unit) are ignored, never deleted; bootstrap reports them as obsolete and adds the new rows. USD and EUR values are placeholders: confirm real rates. Requirements section 4 and 7 still describe the old wording ("one exchange rate per currency", "rates in `cai_dat`"); not edited here.
- Extra module `t3desk/schema.py` is not in the section 12 layout.

## Questions

- UI v2: the seven decisions in `docs/UI-V2-SPEC.md` section 11.
- gbrain research for the UI v2 idea was requested but not done (no gbrain tool in the session; never run against a real gbrain). Run the `mcp_tool` lookup from a prepared machine if wanted.
Inputs the spec (section 13) lists as needed from Viet; adapters are built against fakes until answered:

- Teable: NAS address, version, whether already running; NAS model and CPU type (ARM images).
- Hermes: API reference for running a skill, authentication, skill names for RFQ and RFP, where generated documents are stored.
- gbrain: how to reach the MCP server (command or URL) and which tools to offer.
- Paperclip TODO AI: pull from `cong_viec` or push; for push the endpoint, authentication and task fields.
- Data leaving the LAN: may RFQ and RFP payloads for defence projects go to Hermes, or is a per-project switch needed to block all plugin sends?
- Spec gaps inferred (see notes): `doi_chieu` extra fields, choice sets for `mua_hang`, `moc`, `sai_lech`, `cong_viec` status, placeholder exchange rates (USD 25000, EUR 27000 VND per unit: confirm real rates) and scoring weights; confirm or correct.
