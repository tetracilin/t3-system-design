# T3 Desk requirements

Oct 5, 2026 · @Viet ng

Build one small desktop app, T3 Desk, that lets engineers, sourcing and the PM enter T3 design data into a Teable base on the office NAS, commit it with first-come ID ownership, and see the design decision tree at all times. Plugins let it trigger RFQ and RFP work in Hermes or behind an MCP server, and publish tasks that Paperclip TODO AI can sync. This document is the complete brief for a single build session; where it says "must", the build is wrong without it.

## 1. Scope

Version 1 replaces typing into the T3 spreadsheets (RTM, Phân rã, BOM v2.5) with forms that write to Teable. Teable is the only system of record; the app never writes to Google Sheets or Excel.

In scope:

- Start a project: create the project's tables in Teable from a fixed schema and open it.
- Enter and edit records for requirements, architectures, system nodes, requirement allocation, specifications, OEM candidates, datasheet checks, sourcing rows, milestones and decisions.
- Keep unsent work as local drafts and send it with an explicit Commit.
- Reject a duplicate ID at commit: the first commit keeps the ID, the later user gets a new one.
- Show the decision tree in a docked panel on every screen.
- Compute the next action per node, the warnings and the daily check counters from the data. Trigger external plugins, first for request for quotation (RFQ) and request for proposal (RFP), through Hermes skills and the gbrain MCP server.

* Load plugins that add actions to screens and react to commits, without changing core code.
* Track each RFQ and RFP as a record.
* Publish open tasks to a Teable table that Paperclip TODO AI can sync.

Out of scope for version 1:

- Import from or export to the v2.5 workbooks, other than a CSV export of any table.
- Gantt or schedule views, file attachments, user management, notifications.
- AI running inside the app. AI work is done by external skills and tools that the app triggers through plugins (section 9).
- Deleting records. A record is retired by changing its status.

## 2. Users and roles

About 20 people on one office LAN use the app, most of them junior engineers. Each user picks one role at first start and can change it in Settings. The role decides which screens open by default and which decision tree shows first; it does not block access.

| Role (UI label) | Enters | Reads |
| --- | --- | --- |
| System designer (Thiết kế hệ thống) | Requirements, architectures, system tree, allocation, the two tree gates, final choice of option | Everything |
| Designer (Thiết kế nút) | Specifications, OEM candidates, datasheet checks, chosen candidate for own leaf nodes | Allocation for own nodes, sourcing answers |
| Engineer (Kỹ sư) | Same tables as Designer | Own next actions and warnings |
| Sourcing (Mua hàng) | Vendor, quoted price, lead time, availability per candidate | Candidates that passed their checks |
| PM | Milestones, decisions, change cards | Counters, longest lead time, order-by dates |

Only the System designer may set the two gates (`chot_cap_1`, `chot_cap_2`) and mark an architecture as chosen. The app enforces this by role, not by Teable permissions.

## 3. Technology decisions

The app is a Python program with a local web UI shown in a native window, talking to Teable over its REST API. These choices are fixed for the build; section 13 lists the ones Viet may still overturn.

| Decision | Choice | Reason |
| --- | --- | --- |
| Language | Python 3.11 or later | Runs unchanged on macOS, Linux and Windows; no compile toolchain; the team can read it |
| Window | `pywebview` (uses the OS web view) | Small; no bundled browser |
| Fallback | `--browser` flag serves the same UI to the default browser | Linux machines without WebKitGTK still work |
| UI | Plain HTML, CSS and JavaScript served from `127.0.0.1` on a random free port; no framework, no build step, no CDN | Works on an isolated LAN; one-shot friendly |
| HTTP client | `httpx` | Timeouts and retries in one place |
| Local storage | One SQLite file per user for drafts, cache and settings (standard library `sqlite3`) | No server, survives a crash |
| Token storage | `keyring`; if no keyring backend exists, a config file readable only by the user | Token never in the SQLite file or logs |
| Packaging | PyInstaller one-folder build, made on each OS; also runnable as `python -m t3desk` | No cross-compiling |
| Rejected | Electron (size), Tauri (needs Rust and a build machine per OS), direct PostgreSQL access (bypasses Teable's rules and history) |  |

Teable facts the design relies on, taken from Teable's API reference on 5 Oct 2026:

- Records: `GET`, `POST` and `PATCH` on `/api/table/{tableId}/record`, with `Authorization: Bearer <token>`. Create takes `{"fieldKeyType", "typecast", "records":[{"fields":{…}}]}` and returns each record's `id`, `autoNumber`, `createdTime` and `lastModifiedTime`.
- Listing takes `filter`, `take` (maximum 1000), `skip`, `projection` and `fieldKeyType`.
- Create field (`POST /api/table/{tableId}/field`) accepts `unique` and `notNull` flags. The first-come ID rule in section 5 depends on `unique`.
- Update record has no version or if-match option, so the app does its own stale check (section 5).

All Teable calls must live in one module, `teable_client.py`, behind an interface the rest of the app uses. The build session must check every path and payload against the API reference for the Teable version actually deployed before relying on it, and record the version in the README.

## 4. Data model

One Teable base holds one project, with the fourteen tables below. Field names are the ASCII keys shown; the UI shows Vietnamese labels from a label file. Every ID field is single-line text created with `unique: true` and `notNull: true`.

| Table | ID field and format | Input fields |
| --- | --- | --- |
| `yeu_cau` | `ma_yc`: `R` + number, e.g. `R12` | `mo_ta`, `tieu_chi_nghiem_thu`, `muc` (Bắt buộc / Mong muốn), `uu_tien` (H / M / L), `nguon`, `trang_thai` (Nháp / Đã chốt / Hủy) |
| `kien_truc` | `ma_kt`: `KT-A` … `KT-Z` | `ten`, `nguyen_ly`, `he_con_cap1`, `yc_then_chot`, `uu_diem`, `nhuoc_diem`, `rui_ro`, `chi_phi_uoc_tr`, `tg_uoc_tuan`, `diem_ky_thuat`, `diem_nguon_hang`, `diem_thoi_gian` (1–5), `trang_thai` (Đề xuất / Chọn / Loại), `ly_do` |
| `nut` | `ma_nut`: `N0`; `N1`…; `N1.1`… (three levels at most) | `ma_cha`, `ten`, `chuc_nang`, `loai` (Hệ thống / Cụm / Mua OEM / Tự chế tạo / Phần mềm / Dịch vụ), `so_luong`, `phu_trach`, `ghi_chu` |
| `phan_bo` | `ma_pb`: `PB-001`… | `ma_yc`, `ma_nut`, `kieu` (Mỗi nút phải đạt / Chia ngân sách / Một nút gánh / Kiểm ở cấp hệ thống), `gia_tri_phan_bo`, `don_vi`, `gioi_han_he_thong`, `cach_cong` (Cộng / RSS), `cach_kiem_he_thong`, `ghi_chu` |
| `thong_so` | `ma_ts`: `TS-001`… | `ma_nut`, `ma_yc_goc` (an `R` code or `Dẫn xuất`), `thong_so`, `kieu` (Số / Định tính), `gia_tri_min`, `gia_tri_max`, `don_vi`, `mong_doi`, `muc`, `kiem_chung`, `ghi_chu` |
| `ung_vien` | `ma_uv`: `UV-001`… | `ma_nut`, `hang`, `model`, `cau_hinh`, `xuat_xu`, `gia_cong_bo`, `tien_te`, `loai_gia` (Giá công bố / Ước lượng), `link_datasheet`, `link_gia`, `ngay_kiem_tra`, `nguoi_tim` (Người / AI), `nguoi_kiem_lai`, `trang_thai` (Ứng viên / Chọn / Dự phòng / Loại), `ly_do`, `phuong_an` (e.g. `PA-A;PA-B`) |
| `doi_chieu` | `khoa`: \`\<ma\_uv> | \<ma\_ts>\`, built by the app |
| `mua_hang` | `ma_uv` (one sourcing row per candidate) | `nha_cung_cap`, `don_gia_bao`, `tien_te`, `tinh_trang_nguon` (six-step scale), `tg_cho_tuan`, `thay_the`, `so_bao_gia`, `bao_gia_het_han`, `trang_thai_mua`, `ghi_chu` |
| `moc` | `ma_moc`: `G` + text, e.g. `G4a` | `ten`, `ngay_co_so`, `ngay_du_bao`, `trang_thai` |
| `quyet_dinh` | `ma_qd`: `D` + number | `cau_hoi`, `phuc_vu_moc`, `ngay_du_bao`, `ket_luan`, `ngay_ket_luan` |
| `sai_lech` | `ma_sl`: `SL-001`… | `ngay`, `mo_ta`, `ma_nut`, `nguoi_nhan`, `han`, `trang_thai` |
| `cai_dat` | `khoa` | `gia_tri`. Rows: `ten_du_an`, `ngan_sach_tr`, `so_uv_toi_thieu` (3), `so_uv_toi_da` (5), `chot_cap_1`, `chot_cap_2`, three scoring weights, one exchange rate per currency |
| rfq | ma\_rfq: RFQ-001… or RFP-001… | loai (RFQ / RFP), ds\_ma\_uv, ds\_ma\_nut, nha\_cung\_cap, han\_tra\_loi, trang\_thai (Nháp / Đang tạo / Đã tạo / Đã gửi / Đã có trả lời / Hủy), plugin, ma\_tac\_vu\_ngoai, link\_tai\_lieu, ghi\_chu |
| cong\_viec | ma\_cv: built by the app from source and subject, e.g. CV\|buoc\|N3.1 | nguon (buoc / cho\_nhan / sai\_lech / rfq / canh\_bao), tieu\_de, mo\_ta, ma\_nut, nguoi\_nhan, han, trang\_thai (Mở / Xong / Hủy), cap\_nhat\_luc, ma\_ngoai, dong\_bo\_luc |

Rules for the model:

- Records refer to each other by code held as text (`ma_nut`, `ma_yc`, `ma_uv`, `ma_ts`), not by Teable link fields. The app validates every reference before commit.
- Each table also gets Teable's `autoNumber`, `createdTime`, `lastModifiedTime`, `createdBy` and `lastModifiedBy` fields.
- Calculated values (next action, pass or fail, cost roll-up, warnings) are computed in the app and are not stored in Teable. The one exception is the task rows in cong\_viec (section 9).
- The schema lives in one file, `schema.yaml`, that drives the bootstrap script, the forms, the validation and the Vietnamese labels. Adding a field must need no change outside that file.
- Limits to design for: 100 nodes, 500 specifications, 500 candidates, 3,000 datasheet checks per project.

## 5. Data entry and commit

Nothing a user types reaches Teable until they press Commit. Until then it is a draft in the local SQLite file, and the app says so on every draft row.

Drafts:

- A draft is a new record or a change to an existing record. Drafts survive closing the app.
- When a form for a new record opens, the app proposes the next free ID: the highest number of that kind in Teable and in local drafts, plus one. The user may type a different ID if it matches the format.
- Every form validates on save: ID format, required fields, allowed values, and that every code it refers to exists in Teable or in the user's own drafts.

Commit:

1. Refresh the cache from Teable.
2. Order the drafts so that a record is sent before any record that refers to it (node before its specifications, candidate before its checks).
3. Send new records one at a time. Do not use batch create, so one conflict cannot fail the rest.
4. Show a result line per draft: committed, conflict, or failed with the server's message.
5. Drafts that committed are removed. The others stay as drafts.

Duplicate ID, first come first served:

- The ID fields are unique in Teable, so the server refuses the second record with the same ID. The record already in Teable keeps the ID.
- The later user sees which ID was taken, by whom and when, and the next free ID as a proposal. On accepting, the app renames the draft and rewrites every other local draft that refers to the old ID, then continues the commit.
- The app must never overwrite or delete the first user's record to resolve a conflict.
- Safety net: at start-up and before each commit the app checks that every ID field still has the unique flag, and refuses to commit if one does not. After each create it reads the ID back; if two records carry it, the one with the earlier `createdTime` (then the lower `autoNumber`) wins and the app withdraws its own record and treats it as a conflict.

Editing an existing record:

- Before sending a change, the app re-reads the record. If its `lastModifiedTime` differs from the one the draft was based on, the app shows both versions field by field and the user chooses per field. Teable has no server-side version check, so a second write inside that short window can still be lost; the README must say so.
- An ID cannot be edited after commit.
- There is no delete. Retiring a record means setting its status (`Hủy`, `Loại`), with a reason.

## 6. Decision tree panel

A docked panel on the right of every screen shows the decision tree for the current role. It can be narrowed to a strip but never closed, and one key (F1) widens it again.

Requirements:

- Three trees, one tab each: System design, Designer, Engineer. The user's role picks the first tab.
- Each tree is drawn as a top-down diagram of yes/no questions ending in actions, in SVG, readable without scrolling sideways at a panel width of 360 px.
- The trees are data, not code: one file, `decision_tree.yaml`, loaded at start and reloadable from Settings. Text is Vietnamese.
- A question may name a `check`, a rule from section 7. When it does, the app evaluates it for the selected project, node and user, and highlights the path that is true now. The leaf it reaches is shown as "Bạn đang ở đây".
- An action may name a `screen`. Clicking it opens that screen filtered to the node in question.
- With no node selected, the Designer tree shows no highlight and stays a plain reference.

The content to ship, which Viet may reword in the file later:

```yaml
system_design:            # Thiết kế hệ thống
  - q: "Mọi yêu cầu đã có mã R và mức Bắt buộc / Mong muốn?"
    check: requirements_complete
    no: {do: "Ghi yêu cầu", screen: yeu_cau}
  - q: "Đã có ít nhất 2 kiến trúc để so sánh?"
    check: two_architectures
    no: {do: "Nêu thêm kiến trúc khác về nguyên lý", screen: kien_truc}
  - q: "Đã chọn đúng một kiến trúc, có lý do?"
    check: one_architecture_chosen
    no: {do: "Chấm 3 điểm, chọn một, ghi lý do", screen: kien_truc}
  - q: "Đã liệt kê đủ nút cấp 1 và chốt?"
    check: gate_level_1
    no: {do: "Liệt kê nút cấp 1, rồi chốt. Chưa tách cấp 2.", screen: cay}
  - q: "Nút cấp 1 không mua được nguyên khối đã tách cấp 2 và chốt?"
    check: gate_level_2
    no: {do: "Tách cấp 2, rồi chốt. Chưa tìm OEM.", screen: cay}
  - q: "Mọi yêu cầu Bắt buộc đã phân bổ về nút?"
    check: all_must_allocated
    no: {do: "Phân bổ: mỗi cặp yêu cầu + nút một dòng", screen: phan_bo}
  - q: "Có yêu cầu chia ngân sách đang vượt giới hạn?"
    check: budget_over
    yes: {do: "Chia lại phần của từng nút", screen: phan_bo}
  - q: "Mọi nút lá có người phụ trách, nút nghi chờ lâu xếp trước?"
    check: leaves_assigned
    no: {do: "Giao nút lá", screen: cay}
  - q: "Có nút báo không ứng viên nào đạt?"
    check: any_node_stuck
    yes: {do: "Quyết định: nới yêu cầu, tách nút khác đi, hoặc đổi kiến trúc", screen: cay}
    no: {do: "So sánh phương án ở buổi rà soát tuần", screen: tong_quan}

designer:                 # Thiết kế nút, cho một nút lá
  - q: "Cây hệ thống đã chốt cấp 2?"
    check: gate_level_2
    no: {do: "Chờ. Không viết thông số, không tìm OEM."}
  - q: "Bạn đang mở nút khác chưa xong?"
    check: other_node_open
    yes: {do: "Làm xong nút đó trước", screen: nut}
  - q: "Nút đã có thông số cho mọi yêu cầu được phân bổ?"
    check: node_specs_cover_allocation
    no: {do: "Viết thông số: min hoặc max, đơn vị, mức, mã yêu cầu gốc", screen: nut}
  - q: "Đã có đủ ứng viên (3 đến 5)?"
    check: node_enough_candidates
    no: {do: "Tìm ứng viên, có link datasheet và ngày kiểm tra", screen: nut}
  - q: "Mọi cặp ứng viên × thông số đã đối chiếu, có trích dẫn?"
    check: node_checks_complete
    no: {do: "Đối chiếu datasheet: nguyên văn, số đã quy đổi, trang", screen: nut}
  - q: "Có ứng viên đạt mọi thông số Bắt buộc?"
    check: node_has_passing_candidate
    no: {do: "Báo Thiết kế hệ thống. Không tự nới thông số."}
  - q: "Mua hàng đã có giá báo và thời gian chờ?"
    check: node_sourcing_answered
    no: {do: "Nút chuyển sang Chờ Mua hàng. Bạn được mở nút tiếp theo.", screen: mua_hang}
    yes: {do: "Chọn một ứng viên, ghi lý do, gắn phương án", screen: nut}

engineer:                 # Kỹ sư, mỗi ngày
  - q: "Có bản nháp chưa commit?"
    check: has_drafts
    yes: {do: "Commit. Nếu trùng mã: nhận mã mới mà ứng dụng đề xuất.", screen: commit}
  - q: "Có cảnh báo đỏ ở dòng của bạn?"
    check: my_warnings
    yes: {do: "Sửa trước khi làm việc mới", screen: tong_quan}
  - q: "Có thẻ sai lệch giao cho bạn?"
    check: my_change_cards
    yes: {do: "Làm lại đúng nút bị ảnh hưởng, từ bước thông số", screen: nut}
  - q: "Nút của bạn còn việc tiếp theo?"
    check: my_next_actions
    yes: {do: "Làm theo cây Thiết kế nút", screen: nut}
    no: {do: "Hỏi Thiết kế hệ thống để nhận nút mới"}
  - q: "Cuối ngày: các số kiểm tra đã về 0?"
    check: counters_zero
    no: {do: "Nêu ở giao ban 15 phút sáng mai", screen: tong_quan}
```

Reading rule for the file: questions run in order; a branch that is not written (`yes` or `no` missing) means "go to the next question".

## 7. Checks and next action

All rules live in one pure-Python module, `rules.py`, that takes the cached tables and returns results. It has no network or UI code, and every rule below has a unit test.

Derived values:

- Node level = 0 for the node with no parent, else 1 + number of dots in `ma_nut`. A leaf is a node no other node names as parent.
- A check row passes when `danh_gia_tay` is Đạt, or when it is empty, the specification is numeric and `gia_tri_so` lies within min and max (an empty bound is no bound). `Không rõ` or no value means not checked.
- A candidate result is `Trượt bắt buộc` if any must-have check fails, `Chưa đủ dữ liệu` if any specification of its node is not checked, else `Đạt`.
- Price used = quoted price from `mua_hang` if present, else published price, both converted to million VND with the rates in `cai_dat`.
- Cost rolls up from chosen candidates: leaf = quantity × price; parent = sum of its leaves.
- Budget total per requirement = sum or root-sum-square of `gia_tri_phan_bo`, by `cach_cong`.

Next action for a leaf, first match wins:

| Order | Condition | Text shown |
| --- | --- | --- |
| 1 | No architecture, or more than one, is `Chọn` | Chờ chọn kiến trúc |
| 2 | `chot_cap_1` is not Có | Chờ chốt cấp 1 |
| 3 | `chot_cap_2` is not Có | Chờ chốt cấp 2 |
| 4 | Node has no specification | 2. Viết thông số (n yêu cầu đã phân bổ) |
| 5 | A candidate is `Chọn` and its result is Đạt | Xong |
| 6 | A candidate is `Chọn` and its result is not Đạt | Ứng viên đã chọn chưa đạt |
| 7 | Fewer candidates than the minimum (3 for `Mua OEM`, else 1) | 3. Tìm ứng viên: có n, cần m |
| 8 | Some check of a non-rejected candidate is missing | 4. Đối chiếu datasheet: còn k ô |
| 9 | No candidate has result Đạt | Không ứng viên nào đạt: báo Thiết kế hệ thống |
| 10 | No passing candidate has both a quoted price and a lead time | Chờ Mua hàng |
| 11 | Otherwise | 5. Chọn một ứng viên, ghi lý do |

A non-leaf node shows "x/y nút lá đã xong".

Warnings, shown on the row and counted on the dashboard:

- Tree: parent code does not exist; more than three levels; more than one root; `N1.2` whose parent is not `N1`; specifications or candidates exist before the level-2 gate ("Đi sâu quá sớm"); a leaf without an owner after the gate.
- One node at a time: a person owns two or more leaves whose next action is step 3, 4 or 5. A leaf at "Chờ Mua hàng" does not count.
- Architecture: fewer than two rows; chosen or rejected without a reason.
- Allocation: duplicate requirement-and-node pair; a type other than `Kiểm ở cấp hệ thống` on a non-leaf; budget row without share, limit or method; limits that differ between rows of one requirement; budget total above the limit; `Một nút gánh` with more than one row; a node that has specifications but none for an allocated requirement.
- Specification: numeric without min and max; qualitative without expected value; missing level or source requirement; source requirement not in `yeu_cau`; requirement-and-node pair not in `phan_bo`; attached to a non-leaf.
- Candidate: no datasheet link; no check date; chosen but not passing; two chosen for one node; chosen or rejected without a reason; found by AI and chosen with no human checker; more than the maximum per node.
- Check: candidate and specification belong to different nodes; a result without quoted text and page.
- Sourcing: candidate rejected by the engineer but still open; no availability; no lead time; quote expired; order-by date (date of milestone `G4a` minus lead time) passed, within 14 days, or before the decision date.

Dashboard counters, which must all be 0 at the end of the day: must-have requirements not allocated; allocation pairs missing a specification; budget rows over the limit; passing candidates sourcing has not picked up; chosen candidates without a quote; chosen candidates without a lead time; rows with any warning.

## 8. Screens

The window has three fixed parts: a left navigation list, the working area, and the decision tree panel on the right. A status bar shows the project, the user, the Teable connection state and the number of uncommitted drafts.

| Screen | Purpose | Must have |
| --- | --- | --- |
| Khởi tạo (first run and Settings) | Connect and start | Teable address, token, user name, role; test connection; pick a base or create a project (runs the bootstrap) |
| Tổng quan | Where am I | My leaves with next action; the counters; my warnings; my open tasks |
| Yêu cầu | Enter requirements | Table plus form; number of nodes each requirement is allocated to |
| Kiến trúc | Compare and choose | One card per architecture with the three scores and weighted total; choose button for the System designer |
| Cây hệ thống | Build the tree | Indented tree with level, owner, next action, cost roll-up; add child; the two gate switches |
| Phân bổ | Allocate requirements | Matrix of requirements against leaves; cell click creates or edits the pair; budget total and margin per requirement |
| Nút | Work one leaf | Allocated requirements, specifications, candidates, and a side-by-side comparison of up to five candidates against every specification with quoted value and result |
| Mua hàng | Sourcing queue | "Chờ nhận" list of passing candidates with no sourcing row; form for vendor, quote, lead time, availability; order-by date |
| RFQ / RFP | Track requests | List by status; open the generated document link |
| Mốc và quyết định | PM data | Two simple tables with forms |
| Bản nháp và Commit | Send work | Draft list with validation state; Commit button; result per draft; conflict dialog |

General rules:

- Every table view can filter by node and by owner, sort by any column, and export to CSV.
- Draft rows are marked as drafts wherever they appear.
- A form never needs more than one screen height at 1366 × 768.
- Keyboard: Ctrl or Cmd + S saves a draft, Ctrl or Cmd + Enter opens Commit, F1 widens the decision tree.

## 9. Plugins and integrations

Everything that talks to a system other than Teable is a plugin. The core app must run with no plugin installed, and a plugin must be addable without editing core code.

### 9.1 Plugin contract

- A plugin is a folder holding `plugin.yaml` and `plugin.py`, found in the app's `plugins/` folder or the user's config folder. Plugins are off until enabled in Settings, per machine.
- `plugin.yaml` declares: `id`, `name`, `version`, config keys (with a `secret` flag), the hosts it may call, the actions it adds, and the events it listens to.
- An action names the screens and selections where its button appears (for example `mua_hang.selection`, `nut.current`, `rfq.row`) and the roles that see it.
- Events in version 1: `on_start`, `after_commit` (receives the list of committed changes) and `on_job_poll`.
- `plugin.py` exposes `register(api)`. The `api` object is the only thing a plugin may use:

| Call | What it gives |
| --- | --- |
| `api.read(table, where)` | Cached records, read only |
| `api.rules()` | The results of section 7 |
| `api.draft_create(table, fields)`, `api.draft_update(table, id, fields)` | The only way to write. The draft goes through normal validation and the user's Commit, so the ID rule still holds |
| `api.http(method, url, json)` | HTTP with a timeout, refused unless the host is in the manifest |
| `api.config(key)`, `api.secret(key)` | Settings and tokens |
| `api.job_start(...)`, `api.job_update(...)` | Long-running work the app polls and shows in the status bar |
| `api.notify(text)`, `api.log(...)` | Message to the user; local log |

- Before an action sends anything, the app shows the exact payload and the target host, and the user confirms. The user may skip the preview for the rest of the session, per action.
- Every send is written to a local audit log: time, user, plugin, action, host, record IDs, result.
- A plugin that raises an error is disabled for the session and listed in Settings with the error. It must not stop a commit.
- A plugin never writes to Teable directly and never commits.

### 9.2 RFQ and RFP

A request for quotation (RFQ) starts from one or more selected candidates on the Mua hàng or Nút screen. A request for proposal (RFP) starts from a node, typically when no candidate passes or the node is `Tự chế tạo`, `Phần mềm` or `Dịch vụ`.

1. The app creates an `rfq` draft with a proposed ID and builds the payload below.
2. The user picks which enabled plugin runs it and confirms the preview.
3. The plugin starts the job and returns a job reference; the draft goes to `Đang tạo`.
4. When the job ends, the plugin updates the draft with the document link and `Đã tạo`. The user commits.
5. Sending to the vendor is manual in version 1: the user marks `Đã gửi`, and later `Đã có trả lời` after entering the quote in `mua_hang`.

An RFQ for a candidate whose result is not Đạt needs an extra confirmation. The payload must never contain another vendor's quoted price, the budget, or the scores.

```json
{
  "kind": "RFQ",
  "ma_rfq": "RFQ-003",
  "project": "<ten_du_an>",
  "requested_by": "<user>",
  "language": "vi",
  "reply_by": "2026-10-20",
  "need_by": "<forecast date of milestone G4a, if set>",
  "vendor": "<nha_cung_cap, if known>",
  "items": [
    {"ma_uv": "UV-001", "ma_nut": "N3.1", "ten_nut": "…", "hang": "…", "model": "…",
     "cau_hinh": "…", "so_luong": 2,
     "specs": [{"ma_ts": "TS-003", "thong_so": "…", "yeu_cau": "≥ 10 MPa", "muc": "Bắt buộc"}]}
  ],
  "node": null
}
```

For an RFP, `items` is empty and `node` carries the node's code, name, function, allocated requirements (code, text, acceptance criterion) and specifications.

### 9.3 Hermes skill plugin (`hermes_skill`)

- Config: Hermes API server address, token, and a map from action to skill name (two actions shipped: "Tạo RFQ", "Tạo RFP").
- Behaviour: send the payload to Hermes to run the mapped skill, keep the returned run reference in `ma_tac_vu_ngoai`, poll until it ends, then store the link or text it returns.
- The call that runs a skill on the deployed Hermes version is not specified here. It must be written from the Hermes API reference Viet supplies (section 13), in one function, with a fake Hermes server in the tests.

### 9.4 MCP tool plugin (`mcp_tool`)

- A generic MCP client using the official Python `mcp` package, imported only when the plugin is enabled.
- Config: how to reach the server (a command for stdio, or a URL), and for each action the tool name and a template that maps payload fields to tool arguments.
- Settings lists the tools the server reports, so the user maps actions to tools without editing files.
- Shipped mappings for gbrain: "Tra cứu bối cảnh" (look up what is known about the selected vendor or model) shown beside a candidate, and "Tạo RFQ / RFP" if gbrain offers a tool for it. Results are shown to the user; nothing is written without a draft.

### 9.5 Tasks for Paperclip TODO AI (`task_outbox`)

The app publishes its open work as rows in the `cong_viec` table. That table is the contract: Paperclip TODO AI syncs by reading it through the Teable API, so neither side needs the other's code.

- After every successful commit, and on demand, the plugin rebuilds the task list from the rules: one task per leaf next action (`buoc`), one per candidate waiting for sourcing (`cho_nhan`), one per open change card (`sai_lech`), one per RFQ or RFP past its reply date (`rfq`), and one per person with warnings (`canh_bao`).
- `ma_cv` is built from the source and the subject, so two users' apps produce the same row and the unique flag stops duplicates. A unique conflict here is expected and is treated as "already exists".
- A row is updated only when its title, description, owner, due date or status really changed; `cap_nhat_luc` is set then. A task whose condition no longer holds is set to `Xong`, never removed.
- `ma_ngoai` and `dong_bo_luc` belong to Paperclip. T3 Desk never writes them.
- Version 1 is one-way: closing a task in Paperclip does not change T3 data. The task closes when the data says the work is done.
- Optional push: if a Paperclip address and token are configured, the plugin also posts changed tasks to it. That call is written from the Paperclip TODO AI API Viet supplies; without it, only the table contract is built.

## 10. Teable on the NAS

The app uses the Teable instance on the office NAS and nothing else for shared data. If no instance is running yet, the repository must contain what is needed to start one.

- `deploy/docker-compose.yml` for Teable Community with PostgreSQL and Redis, image tags pinned to exact versions (no `latest`), data in named volumes on the NAS.
- `deploy/.env.example` listing every required variable, with `PUBLIC_ORIGIN` set to the address users type, without a trailing slash.
- `deploy/README.md`: start, stop, upgrade, and a nightly backup of the PostgreSQL volume to a NAS share with a restore test.
- Teable's own guide asks for Linux, at least 4 GB RAM, 2 CPU cores and 40 GB of disk. The README must tell Viet to check the NAS against that before starting.

Bootstrap script, `t3desk bootstrap`:

- Input: Teable address, a token allowed to create tables and fields, and either a base ID or a project name.
- Creates every table and field in `schema.yaml`, with `unique` and `notNull` on ID fields and the allowed values on choice fields.
- Safe to run again: it adds what is missing, changes nothing that exists, and reports any field whose type or unique flag differs from the schema.
- Writes the default `cai_dat` rows and saves the table IDs in the app's settings.
- Ends by creating two records with the same ID in a scratch table and confirming the second is refused. If it is not refused, the script fails with a clear message, because the first-come rule would not hold.

Each person uses their own Teable token, limited to reading, creating and updating records in the project base, so Teable's history shows who wrote what.

## 11. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Platforms | Windows 10 and 11, macOS 12 or later (Intel and Apple silicon), Ubuntu 22.04 or later. One codebase, no OS-specific branches outside a single `platform.py` |
| Size | Packaged folder at most 80 MB; at most 200 MB of RAM in normal use; window visible within 3 seconds on an ordinary office laptop |
| Dependencies | At most six third-party Python packages in the core (`pywebview`, `httpx`, `keyring`, `pyyaml` and what they need). The `mcp` package only with its plugin |
| Network | The core needs only the NAS. No call to any other host, no CDN, no fonts or scripts fetched at run time, no update check, no telemetry. Plugins call only the hosts in their manifest |
| Working without the NAS | The app opens, shows the last cached data marked with its age, and lets the user keep drafting. Commit is disabled until Teable answers |
| Speed | Any screen draws within 1 second on the cache at the size limits in section 4. A refresh from Teable pages with `take=1000` and shows progress |
| Language | All UI text in Vietnamese, from one label file. Code, comments, logs and the README in English, plus a one-page Vietnamese quick start |
| Safety of data | No delete anywhere. No write outside the draft-and-commit path. Tokens never written to logs, the SQLite file or the audit log |
| Errors | Every failed call shows what failed, the server's message and what the user can do. No silent failure and no blank screen |
| Logs | One rotating log file per user in the user's config folder |

## 12. Deliverables and acceptance tests

The build session delivers one repository that runs from source on all three systems and passes the tests below against a fake Teable server it also writes.

Repository layout:

```
t3desk/            app package: main, server, teable_client, store (SQLite), rules, commit, plugins_api, platform
t3desk/ui/         index.html, app.js, style.css, tree.js (decision tree drawing)
t3desk/data/       schema.yaml, labels_vi.yaml, decision_tree.yaml
plugins/           hermes_skill/, mcp_tool/, task_outbox/
deploy/            docker-compose.yml, .env.example, README.md
tests/             fake_teable.py, fake_hermes.py, fixtures/, test_*.py
scripts/           build_windows.ps1, build_macos.sh, build_linux.sh, smoke.py
README.md, HUONG_DAN.md, pyproject.toml
```

`tests/fake_teable.py` is an in-process HTTP server that implements the record, table and field calls the client uses, including the unique flag, `autoNumber`, `createdTime` and `lastModifiedTime`. All tests run against it with `pytest`, with no network.

Acceptance tests, each an automated test unless marked manual:

1. Bootstrap creates the fourteen tables on an empty base. A second run changes nothing and reports no difference.
2. Users A and B both draft `UV-007`. A commits, then B commits. B is told the ID was taken by A, accepts `UV-008`, and B's drafted checks that pointed at `UV-007` now point at `UV-008`. A's record is unchanged.
3. A and B commit the same new ID at the same moment from two threads. Exactly one record with that ID exists afterwards, and the other user holds a conflict.
4. With the unique flag removed from one ID field, commit is refused and the message names the field.
5. A edits a record B changed after A loaded it. A sees both versions and chooses per field.
6. Drafts listed as check, candidate, node are committed in the order node, candidate, check.
7. One conflicting draft does not stop the other drafts in the same commit.
8. With the server stopped, the app starts, shows cached data with its age, saves a draft, and keeps it after a restart. Commit is disabled.
9. Rules: on the fixture project (root, five level-1 nodes, four leaves under two of them, as in the v2.5 pressure-tank example) the hydrophone leaf shows `Xong`, the digitiser leaf shows step 3 with "có 2, cần 3", untouched leaves show step 2 with their allocation count, and the counter for allocation pairs missing a specification is 1. Each warning in section 7 has one test that triggers it and one that does not.
10. The decision tree draws from `decision_tree.yaml`; changing one question's text and reloading changes the panel; the highlighted path changes when the fixture data changes.
11. With the `plugins/` folder empty the app starts and commits normally. A plugin that raises on load is disabled and listed, and commit still works.
12. A plugin call to a host not in its manifest is refused.
13. RFQ flow against `fake_hermes.py`: the preview shows the payload, the payload holds no price, budget or score, and the flow ends with a committed `rfq` record in state `Đã tạo` with a link.
14. Task outbox: two apps on the same data produce one row per task; when a leaf reaches `Xong` its task becomes `Xong`; a value placed in `ma_ngoai` survives every later update.
15. No HTTP leaves the process except through the one client with its host allow-list (test by patching sockets).
16. Manual: `python -m t3desk` opens a window and `--browser` opens the default browser, on each of the three systems. The build scripts produce a runnable folder.

The session must end with a short report: which tests pass, what it could not verify (a real Teable instance, the real Hermes and gbrain servers, packaging on systems it did not run on), and every place it departed from this document and why.

Suggested opening message for the build session:

```
Build the application described in the attached requirements document, T3 Desk requirements.
Treat every "must" as binding. Follow sections 3, 4 and 12 exactly for stack, schema and layout.
Write the fake Teable server and the tests first, then the core, then the three plugins.
Do not invent endpoints for Hermes, gbrain or Paperclip: use the references attached, and where
none is attached, build the adapter against the fake server and mark it clearly as unverified.
Finish with the report section 12 asks for.
```

## 13. Assumptions and open questions

These are choices made without Viet's confirmation. The build can start on them; changing one later costs the amount shown.

| # | Assumption | If wrong |
| --- | --- | --- |
| 1 | Python with `pywebview`, not Tauri or Electron | Rewrite of the shell and packaging; rules, schema and tests carry over |
| 2 | "Designer, system design and engineer" map to the three trees in section 6, and sourcing and PM use the app without a tree of their own | Edit `decision_tree.yaml` only |
| 3 | One Teable base per project | Schema gains a project column; moderate rework |
| 4 | Teable is the only store; the v2.5 workbooks are not imported | An import script, about a day |
| 5 | References between records are codes held as text, not Teable link fields | Views inside Teable itself are less convenient; changing later is a schema migration |
| 6 | A leaf waiting for sourcing does not block its owner from opening the next leaf | One rule in `rules.py` |
| 7 | Paperclip TODO AI syncs by reading the `cong_viec` table; push is optional | Write the push call once the API is supplied |
| 8 | Task sync is one-way in version 1 | Two-way needs a rule for who wins on status |
| 9 | The app name is T3 Desk | Rename |

Inputs the build session needs from Viet. Without them the matching adapter is built against a fake and marked unverified:

- [ ] Teable: address on the NAS, version, and whether it is already running. NAS model and CPU type, since the images may not run on an ARM NAS.
- [ ] Hermes: API reference for running a skill on the deployed version, how to authenticate, the skill names for RFQ and RFP, and where the generated document is stored.
- [ ] gbrain: how to reach the MCP server (command or URL) and which tools should be offered.
- [ ] Paperclip TODO AI: whether it will pull from `cong_viec` or wants a push, and for push the endpoint, authentication and task fields.
- [ ] Data leaving the LAN: Hermes runs outside the NAS. Decide whether RFQ and RFP payloads for defence projects may be sent there, or whether a per-project switch must block all plugin sends.

## 14. Sources

Teable documentation opened on 5 Oct 2026:

- [Create records](https://help.teable.ai/en/api-reference/record/create-records)
- [List records](https://help.teable.ai/en/api-reference/record/list-records)
- [Update record](https://help.teable.ai/en/api-reference/record/update-record)
- [Create field](https://help.teable.ai/en/api-reference/field/create-field)
- [Docker Compose deployment](https://help.teable.ai/en/deploy/docker)

The data model, rules and step numbers come from the T3 templates v2.5 (RTM, Phân rã, BOM) and the engineer handbook produced earlier in this work. Attach those files to the build session as reference.
