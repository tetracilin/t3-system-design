# UI area notes: inferences and departures

Files: t3desk/{server,main,platform}.py, t3desk/ui/{index.html,app.js,style.css,tree.js},
t3desk/data/labels_ui_vi.yaml, tests/test_server.py, scripts/smoke.py.

## Inferences (spec silent)
- Roles are stored as the keys `system_designer`, `designer`, `engineer`, `sourcing`, `pm` (setting `role`). Default tree tab: system_designer -> System design,
  designer -> Designer, engineer, sourcing and PM -> Engineer (assumption 2 gives sourcing and PM no tree of their own). Default screen: system_designer Yêu cầu,
  designer Nút, engineer Tổng quan, sourcing Mua hàng, PM Mốc và quyết định; no user or role yet -> Khởi tạo.
- Role enforcement (server side, at draft save and again at commit): any draft touching `cai_dat` keys `chot_cap_1` / `chot_cap_2`, and any `kien_truc` draft whose
  `trang_thai` is `Chọn`, needs role `system_designer`. Everything else is open. Field and key names for this are constants in server.py (the rules module does the same).
- Drafts are overlaid on the cached tables before rules run, so draft rows count in warnings, next actions, counters and the decision tree highlight. The spec says rules read "cached tables";
  this is a deliberate departure so the tree reacts to what the user just typed and so `has_drafts` works. `Context.drafts` is the number of local drafts.
- Table views show the ID field plus the first non-longtext fields (at most 9 columns); every field is in the form. Computed columns (`n_nodes` on yeu_cau, level / cost / next action on nut,
  result / price on ung_vien, order-by on mua_hang) come from rules and are never stored.
- Node filter: a row matches node X when its node is X or a descendant (`X.`...), or, on `nut`, its parent is X. Tables without `ma_nut` (doi_chieu, mua_hang) use the candidate's node.
  Owner filter uses `phu_trach`, else `nguoi_nhan`, else the node's owner.
- A tree action that names a screen opens it with the node filter set to the node selected in the panel (selecting a node: click a row on Cây hệ thống, or open a leaf on Nút).
- With no node selected the Designer tree is forced to "no highlight, plain reference" in server.py, because some designer checks answer without a node.
- Weighted architecture total = sum(score x weight) / sum(weights of scored criteria); with no weights in `cai_dat` the three criteria count equally. Result is on the 1-5 scale.
- Gate switches create or update a `cai_dat` draft (`Có` / `Không`). The Khởi tạo screen also lists the `cai_dat` table (budget, min and max candidates, weights, rates) as an ordinary table with forms.
- Creating a project needs a Teable space ID (the client's `create_base` takes one), so Khởi tạo has a "space" field next to base ID and project name. There is no base picker: `teable_client` has no list-bases call.
- Updates send only changed fields; an emptied field is sent as null so it clears. The `doi_chieu` key is built by the form as `<ma_uv>|<ma_ts>`.
- The save-draft call refuses invalid data (422 with a per-field list), so a draft normally starts valid. The draft list still re-validates every draft, because a reference can break later.
- Commit conflicts and stale edits: the UI shows a dialog from the first conflict or stale result; the user accepts the proposed ID (or types another) and presses Commit again. Stale: radio per field "mine / theirs".
- UI text: `labels_vi.yaml` already held tables, fields and rule texts. The screen texts live in `labels_ui_vi.yaml` (section `ui`) and are merged into the same label set by `server.load_ui_labels()`.
  Error texts are keyed by error code (`err_<code>`) and say what failed and what to do; the server's own message is shown under them.
  YAML 1.1 reads bare `yes`/`no` keys as booleans, so those labels are `answer_yes` / `answer_no`.
- Security of the local server: bound to 127.0.0.1, `Host` header must be 127.0.0.1 or localhost with the right port, every `/api` call needs the per-run `X-T3-Session` header (injected into index.html),
  POST needs `application/json`, and a CSP of `default-src 'self'` is sent.
- Window code (pywebview, `--browser`, fallback when the window fails) lives in `t3desk/main.py`; `server.py` has only the HTTP layer and the App logic.
- `platform.py` holds the config folder per OS, `T3DESK_HOME` override, opening the browser, the shortcut key name and "is pywebview importable".
- The panel mode (open / strip / wide) is kept in `localStorage` as a convenience only; the page works without it.

## Departures
- Plugin buttons on screens (section 9) are not in the UI: `plugins_api` belongs to another area. When it exists, actions can be added to `app.js` per screen.
- "Draft rows are marked as drafts wherever they appear": done on table views, Nút sub-tables, the comparison matrix, the allocation matrix, architecture cards and the tree. The tree panel itself has no draft marker.
- The CSV export is built by the server and downloaded with a Blob link. In some pywebview back ends a blob download may do nothing; use `--browser` there (unverified, see below).
- `Cây hệ thống` has no drag or inline edit: add child opens the node form with the parent filled in and the next free child ID proposed.
- Tests were written together with the code, not strictly test-first for each item.

## Unverified
- Not run in a real pywebview window or on macOS and Linux. Headless Edge on Windows ran a scripted walk through all 11 screens, the draft form (invalid then valid save), Ctrl+Enter, F1, the collapse toggle,
  a tree action click and checked the SVG is 328 px wide in the 360 px panel with no horizontal scroll. That walk is a scratch script, not part of the repo tests; the repo tests cover the server, labels and JS syntax (via `node --check` when node exists).
- Keyboard shortcut Ctrl or Cmd + S on pywebview's Windows and macOS back ends (the key event reaches the page in a browser; native menus may intercept it elsewhere).
- Everything the other notes list as unverified against a real Teable still applies: the UI only calls the fake.
