# task_outbox

Rebuilds the `cong_viec` task rows from the rules after every commit and on demand (action
"Cập nhật danh sách công việc"). It only creates local drafts; the user's Commit sends them.

| nguon | one task per | `ma_cv` |
| --- | --- | --- |
| buoc | leaf whose next action is a work step (rows 4, 6, 7, 8, 9, 11 of the rules table) | `CV\|buoc\|<ma_nut>` |
| cho_nhan | passing candidate with no `mua_hang` row | `CV\|cho_nhan\|<ma_uv>` |
| sai_lech | change card with status Mở | `CV\|sai_lech\|<ma_sl>` |
| rfq | RFQ/RFP in state Đã gửi past `han_tra_loi` | `CV\|rfq\|<ma_rfq>` |
| canh_bao | person (node owner) with at least one warning | `CV\|canh_bao\|<name>` |

Rules: deterministic `ma_cv`; unique conflict = already exists (draft dropped); update only on a
real change of title, description, owner, due date or status; a task whose condition ended is set
to Xong, never removed; `ma_ngoai` and `dong_bo_luc` are never written. Task texts are in
`labels.yaml`.

## UNVERIFIED

The optional Paperclip push (`push_to_paperclip`: `POST <paperclip_url>/api/tasks`, bearer token)
is an assumption; no Paperclip TODO AI API reference exists. Without `paperclip_url` and
`paperclip_token` only the table contract runs, which is the tested part.
