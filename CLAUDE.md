# CLAUDE.md

# T3 Proposal Tool

Desktop app for TECOTEC Technologies' T3 design workflow. Engineers, sourcing and the PM enter
design data through forms; the app stores it in a Teable base on the office NAS, enforces
first-come ID ownership at commit, shows a decision tree on every screen, and reaches outside
systems (Hermes skills, the gbrain MCP server, Paperclip TODO AI) only through plugins.

## Source of truth

- `docs/REQUIREMENTS.md` is the specification ("T3 Desk requirements"). Read it fully before
  writing code. Every "must" in it is binding.
- If the code and the requirements disagree, the requirements win. If the requirements are
  wrong or silent, stop and ask; do not guess and do not quietly depart from them.
- `docs/reference/` holds the T3 templates v2.5 (RTM, Phân rã, BOM workbooks) and the engineer
  handbook. They explain where the data model and rules come from. They are reference only.
- `STATUS.md` is the running state of the project (see "End of every session").

## Stack (fixed, do not change without asking)

- Python 3.11+. Window via `pywebview`; `--browser` flag serves the same UI to the default browser.
- UI is plain HTML, CSS and JavaScript in `t3desk/ui/`, served from `127.0.0.1`. No framework,
  no build step, no CDN, no fonts or scripts fetched at run time.
- `httpx` for HTTP, standard-library `sqlite3` for drafts and cache, `keyring` for tokens,
  `pyyaml` for data files. No other third-party package in the core without asking.
- The `mcp` package is imported only inside the `mcp_tool` plugin.
- Packaging with PyInstaller, built on each OS by the scripts in `scripts/`.

## Layout

```
t3desk/         main, server, teable_client, store, rules, commit, plugins_api, platform
t3desk/ui/      index.html, app.js, style.css, tree.js
t3desk/data/    schema.yaml, labels_vi.yaml, decision_tree.yaml
plugins/        hermes_skill/, mcp_tool/, task_outbox/
deploy/         Teable docker-compose, .env.example, README
tests/          fake_teable.py, fake_hermes.py, fixtures/, test_*.py
scripts/        build_windows.ps1, build_macos.sh, build_linux.sh, smoke.py
docs/           REQUIREMENTS.md, reference/
```

## Commands

```
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                          # all tests, no network, uses tests/fake_teable.py
python -m t3desk                   # native window
python -m t3desk --browser         # same UI in the default browser
python -m t3desk bootstrap --help  # create tables and fields in a Teable base
python scripts/smoke.py            # start, load one screen, exit
```

Run `pytest -q` before saying any task is done. Report the real result, including failures.

## Rules that must never be broken

1. **Nothing is deleted.** No delete call to Teable anywhere. Records are retired by status.
2. **One write path.** Every write to Teable goes draft → validation → Commit. Plugins and
   background code create drafts; they never write to Teable and never commit.
3. **First come keeps the ID.** ID fields are `unique` in Teable. On a duplicate, the record
   already in Teable is never changed; the later user gets a new ID and local references are
   rewritten. Commit is refused if an ID field has lost its unique flag.
4. **One Teable module.** All Teable HTTP lives in `t3desk/teable_client.py`. Check each path
   and payload against the API reference for the deployed Teable version before relying on it.
5. **Do not invent external APIs.** For Hermes, gbrain and Paperclip TODO AI, use only what is
   in `docs/reference/`. If no reference is there, build against the fake server and mark the
   adapter `UNVERIFIED` in code, in the README and in `STATUS.md`.
6. **No stray network.** The core talks only to the configured Teable address. Plugins call
   only hosts in their manifest. No telemetry, no update check.
7. **Preview before send.** A plugin action shows the exact payload and target host before
   sending. RFQ and RFP payloads never contain another vendor's price, the budget, or scores.
8. **Secrets stay out** of logs, the SQLite file, the audit log, test fixtures and git.
9. **Schema changes go in `schema.yaml` only.** Forms, validation, labels and the bootstrap
   script are driven by it. Do not hard-code a field name elsewhere.
10. **Rules are pure.** `rules.py` has no network and no UI code. Every rule has a test that
    triggers it and a test that does not.

## Conventions

- UI text is Vietnamese and comes from `labels_vi.yaml`; no Vietnamese string literals in code.
- Code, comments, commit messages, logs and docs are in English. `HUONG_DAN.md` is the
  one-page Vietnamese quick start.
- Field and table names are the ASCII keys in the requirements (`ma_nut`, `ung_vien`, …).
  Do not rename or translate them.
- Write the failing test first for anything in section 12 of the requirements, then the code.
- Small functions, type hints, no cleverness. Junior engineers will read this code.
- Every failed call shows the user what failed, the server's message and what to do next.
  No silent failure, no bare `except`.
- OS-specific code only in `t3desk/platform.py`.

## Working with Viet

- Viet works on this in short sessions and switches context often. Keep answers short and
  lead with the result.
- Ask before: adding a dependency, changing the stack or schema, touching `deploy/`,
  running anything against the real NAS, or pushing to a remote.
- Say plainly what was run and what was not. Never describe a test as passing unless it ran
  in this session.
- Commit in small steps on a feature branch with a clear message. Do not push unless asked.

## End of every session

Update `STATUS.md` so the next session (or Viet, after a break) can pick up in one minute:

- **Done:** what now works, with the test names that prove it.
- **Next:** the next three steps, in order.
- **Unverified:** anything not tested against the real Teable, Hermes, gbrain or Paperclip,
  and any OS the app was not run on.
- **Departures:** every place the code differs from `docs/REQUIREMENTS.md`, and why.
- **Questions for Viet:** decisions that are blocking.

## Build order

1. `tests/fake_teable.py` and the tests for commit and the ID rule.
2. `schema.yaml`, `teable_client.py`, `store.py`, bootstrap.
3. `rules.py` with its tests, using the pressure-tank fixture.
4. Commit flow, then the screens, then the decision tree panel.
5. Plugin API, then `task_outbox`, `hermes_skill`, `mcp_tool`.
6. Packaging scripts, README, `HUONG_DAN.md`, final report.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
