# STATUS

Merged from `docs/notes/*.md` (commit, foundation, packaging, plugins, rules, ui). Test results are not recorded here; run the suite and report the real output. Last full run (9 Oct 2026, after UI v2): 510 passed, 1 skipped (a placeholder for the Hermes preview test).

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
- Weekly review (9 Oct 2026, `docs/designs/review-first-pilot.md`, eng-reviewed): screen `ra_soat` ("Rà soát tuần") with `GET /api/review` and `POST /api/review/end`; findings are `sai_lech` records ("Ghi nhận xét" form with `[QT|PĐ] [code]` prefix, close with a reason); `my_findings` on Tổng quan; rule warnings on draft save (`tree_too_early` shows on the spec form); print stylesheet. Tests: `test_rules.py` (`req_no_criterion`, `arch_multi_chosen`, `finding_no_owner` in `WARNING_CASES`), `test_server.py` (`test_review_*`, `test_end_review_*`, `test_overview_lists_my_open_findings_only`, `test_save_draft_returns_*too_early*`, `test_finding_without_a_node_saves`, role guards), `test_flow_predator.py::test_review_loop_two_users`. Checked by hand in a browser against the fake Teable (review screen, remark form, close with reason, end review; no console errors).
- UI v2 (9 Oct 2026, `docs/UI-V2-SPEC.md`, built on Viet's choice of "Full UI v2 spec"): four panes (menu + decision-tree checklist, list or breakdown chart, inline-edit table, context + notes + Hermes placeholder), `ui/{app,grid,notes,keys}.js`, new table `ghi_chu` (15 tables), `partial` drafts, `/api/{notes,context,assistant}`, menu counts, chart dots, one shortcut list (`keys.js`) with palette (Ctrl+K) and cheat sheet (?). Tests: `tests/test_ui_static.py` (spec section 10 tests 1, 2, 4, 5, 6; test 6's preview part is a skipped placeholder), `tests/test_server.py` (`test_partial_*`, `test_note_*`, `test_only_the_author_*`, `test_two_users_taking_the_same_note_id_*`, `test_context_*`, `test_state_carries_menu_counts_*`, `test_assistant_is_a_placeholder_*`, `test_chart_nodes_*`). Checked by hand in Chrome against the fake Teable: typing into a cell, partial row with red cell and message, choice and reference drop-downs, notes with preview and save, chart keyboard (Alt+2, arrows, Enter), tabs (Ctrl+PageDown), palette, cheat sheet, F1 tree, all 12 screens render without console errors.

## Next

- **Next (user test):** the weekly review (`docs/designs/review-first-pilot.md`) and UI v2 are both built. Before the first session: run `t3desk bootstrap` on the pilot base (adds `nut.ma_kt`, `ghi_chu`, `chu_ky_ra_soat_ngay`), then watch one named junior use it. Office hours (8 Oct) advised freezing UI v2 until after that session; Viet chose to build it first (9 Oct), so treat the layout as a guess to be tested.
- **Viet to fill in:** pilot junior: ___ · project: ___ · reviewer: ___ · session 1 date: ___
- Spec section 10 test 8 (tab through the four panes without a mouse, on Windows, macOS, Ubuntu) is manual and not done; so is running the UI inside the pywebview window.
- Hermes: the panel is a placeholder. Enabling it needs plugin actions wired to screens (REQUIREMENTS 9.1) and the Hermes API details; the preview-payload test is a skipped placeholder in `tests/test_ui_static.py`.
- Electron, Hyprland and Quickshell were requested but conflict with CLAUDE.md (stack fixed), requirements section 3 (Electron rejected), the 80 MB / 200 MB limits and Windows/macOS/Ubuntu support (Hyprland and Quickshell are Linux-only). Not started; needs an explicit decision.
- Existing Teable bases need `t3desk bootstrap` run again to add the new `nut.ma_kt` column.
- Decide: two chosen architectures give no warning (section 7 silent); nodes have no status to retire them; any role may set an architecture to `Loại`.
- Plugins have no UI wiring (Settings page, buttons, preview dialog); the caller must call `host.start()`, `host.after_commit(report)`, `host.poll_jobs()` and supply the confirm hook.
- Test 15 (socket patching, whole app) is not in the plugins area.
- Record the deployed Teable version in README.md; verify image tags in `deploy/docker-compose.yml`.
- Check that the plugin loader finds `plugins/` inside a frozen PyInstaller app.
- Run the build scripts on each OS (PyInstaller is not installed in the venv).

## Unverified

- UI v2 was exercised only in desktop Chrome against `tests/fake_teable.py` (scratch server, not part of the repo). Not run: pywebview window, Edge/Firefox/Safari, macOS, Ubuntu, a real Teable with more than a few hundred rows (grid redraws the whole body on every cell save; fine at the section 4 limits on paper, not measured), keyboard shortcuts inside pywebview (`Ctrl+K`, `F1`, `Alt+n` may be taken by the OS or window).

- Teable: verified against release.2026-08-19T02-25-59Z.2698 on 5 Oct 2026 (see `docs/notes/teable-live.md`); still unverified there: two different real users, more than 1000 rows, limited-permission tokens, rate limits, non-UTC date fields.
- Hermes adapter: follows the documented Runs API (`POST /v1/runs`, `GET /v1/runs/{id}`, Idempotency-Key; see `docs/reference/hermes-api-server.md`) but never run against a real Hermes. UNVERIFIED: run `status` values, where documents are stored, real skill names (`rfq` / `rfp` are placeholders), whether the skill obeys the JSON-reply instruction.
- gbrain MCP adapter: remote HTTP MCP (`https://<host>/mcp`, bearer token; see `docs/reference/gbrain-mcp.md`), read-only (write tools blocked in code). Never run against a real gbrain. UNVERIFIED: `search`/`query` argument names and response shapes. The guessed RFQ/RFP mapping was removed.
- Paperclip push (`POST <url>/api/tasks`): invented; only the `cong_viec` contract is tested. UNVERIFIED. Paperclip's MCP page and the webhooks plugin (outbound events only) do not give an inbound task API; waiting for Paperclip's HTTP API docs.
- Docker image tags and Teable environment variable names in `deploy/`; backup and restore scripts never run on a NAS.
- Packaging on all three OSes; pywebview window on any OS; macOS and Linux never run; Ctrl or Cmd + S in pywebview; blob CSV download in some pywebview back ends.
- UI walk in headless Edge on Windows was a scratch script, not part of the repo tests.

## Departures

- UI v2 (9 Oct 2026): the four-pane layout replaces requirements section 8's three parts; every add or edit is a cell edit, not a form; new table `ghi_chu` (15 tables, acceptance test 1 now counts 15); `POST /api/draft` takes `partial: true` so a half-filled row is a draft that Commit reports as failed until fixed; the Kiến trúc cards are replaced by the grid with a "Chọn" button and a weighted-total column; the allocation matrix and the comparison matrix stay as compact views above their tables.
- UI v2 keys: single letters N (notes), G (go to), ? (cheat sheet) work outside the table only, because typing in the table edits the cell; alternatives work everywhere (Alt+N, Ctrl+K, Ctrl+/). Ctrl+Enter opens Commit with its button focused, it does not send (requirements 8, "opens Commit").
- Dialogs that remain beyond the two in the spec (architecture reason, discard confirm): conflict and stale resolution (commit), closing reason and remark kind (weekly review), Ctrl+K palette, ? cheat sheet, F1 tree diagram.

- Review mode (9 Oct 2026): three new warnings not in requirements section 7 (`req_no_criterion`, `arch_multi_chosen`, `finding_no_owner`); a 12th screen `ra_soat` (section 8 lists 11); `sai_lech` is used for review findings and is written by the System designer (section 2 gives change cards to the PM; the PM may also cancel them); new `cai_dat` keys `chu_ky_ra_soat_ngay` (default 7, seeded by bootstrap) and `ngay_ra_soat_cuoi` (created by the first "Kết thúc rà soát", not seeded); `POST /api/draft` now returns `warnings`. "Kết thúc rà soát" only creates a draft: until it is committed the review date is local to that machine.

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
