# Plugins area: inferences and departures

Files: `t3desk/plugins_api.py`, `t3desk/rfq.py`, `plugins/{hermes_skill,mcp_tool,task_outbox}/`,
`tests/fake_hermes.py`, `tests/test_plugins.py`.

## UNVERIFIED (no reference exists)
- Hermes wire format (`POST /v1/skills/{skill}/runs`, `GET /v1/runs/{ref}`, bearer token, states `succeeded`/`failed`, `link`/`text`) is invented; it lives only in `run_skill` and `tests/fake_hermes.py`. Default skill names `rfq` / `rfp` are placeholders.
- gbrain MCP mappings (`tra_cuu_boi_canh` -> tool `query`; RFQ/RFP -> no tool) are guesses. The MCP client is tested only with a fake session; the real `mcp` stdio/URL path was never run.
- Paperclip push (`POST <url>/api/tasks`, body `{"tasks": [...]}`) is invented. Only the `cong_viec` table contract is tested.

## Inferences about the contract (section 9.1 was silent)
- `plugin.yaml` extras: `writes: [tables]` (least privilege; the api refuses draft calls for other tables), config keys with `secret`/`default`, hosts as `host`, `host:port` or `{config:key}` (host taken from a config URL, because the Hermes/Paperclip/MCP address is user configured).
- Action screens use `screen.selection` form; roles use ASCII keys `system_designer, designer, engineer, sourcing, pm`.
- Plugin binds handlers in `register(api)` with `api.action(id, fn)` and `api.on(event, fn)`; both must be declared in the manifest.
- Extra api calls beyond the section 9.1 table: `today`, `tables`, `next_id`, `find_draft`, `list_drafts`, `draft_discard` (local unsent draft only), `check_host`, `confirm_send`, `audit_send`. `read` returns flat dicts plus `_record_id`, `_modified`.
- `draft_update` merges into an existing draft for the same ID, and drops values equal to the current ones (returns None when nothing changes). This gives "update only on a real change".
- The api (not only task_outbox) refuses `cong_viec.ma_ngoai` and `dong_bo_luc` (defense in depth).
- Preview happens inside `api.http` when a request carries a JSON body; GET polling without body is audited but not previewed. Confirm hook returns True / False / `"session"` (skip for rest of session, per plugin and action). With no hook the answer is "decline".
- Audit log: `<data_dir>/audit.jsonl`, plugin log `<data_dir>/plugin.log`; both pass through `scrub`, which masks every known plugin secret value. Payload bodies are not in the audit log. Stored secrets use `store.save_secret` with service `t3desk-plugin:<id>`.
- Enabled flag per machine: SQLite setting `plugins_enabled`. Plugin config: setting `plugin.<id>.<key>`.
- `HostNotAllowed` raised inside a plugin that does not catch it disables that plugin (it is an error like any other); `SendDeclined` (user said no) does not.
- Jobs are in memory only (not persisted over restart). `poll_jobs()` is called by the app timer; only the owning plugin is asked.
- RFQ ID: `RFQ-nnn` and `RFP-nnn` are separate sequences (`next_free_id` with prefix). RFQ `ds_ma_nut` is the candidates' nodes; `so_luong` is the node quantity. Requirement text `yeu_cau` is built as `>= min unit`, `<= max unit`, `min - max unit` or the expected text for qualitative specs. RFP `node.yeu_cau` lists code, text and acceptance criterion only (never allocated budget values).
- Payload guard: keys whose `_` tokens include gia, price, budget, score, diem, cost, sach or quote are rejected (`ForbiddenContent`). Values in free text are not scanned.
- Extra confirmation for non-Đạt candidates is a callback `extra_confirm`; without approval no draft is created.
- core code (not a plugin) creates the `rfq` draft through `host.core`, an unrestricted api object.
- task_outbox: a task per leaf only for next-action rows 4, 6, 7, 8, 9, 11 (leaf owner has work); rows 1-3 (global waits), 5 (Xong) and 10 (Chờ Mua hàng, covered by `cho_nhan`) make no `buoc` task. `canh_bao` covers warnings that have an owner. `rfq` task: state `Đã gửi` and `han_tra_loi` before today. Task texts come from `plugins/task_outbox/labels.yaml`. On a `cong_viec` conflict the local draft is dropped; that key is skipped in that same rebuild and re-evaluated after the next cache refresh.
- `cap_nhat_luc` is set only on a real change; it is a date, so a same-day change leaves it unchanged and it is then omitted from the update draft.

## Not done / limits
- No UI wiring (Settings page, buttons, preview dialog): this area delivers the host and api only. The caller must call `host.start()`, `host.after_commit(report)`, `host.poll_jobs()` and supply the `confirm` hook.
- Test 15 (socket patching, whole app) is not in this area; plugin HTTP goes only through `PluginApi.http`.
- `tests/test_plugins.py` takes about 65 s (many fake-server starts).
