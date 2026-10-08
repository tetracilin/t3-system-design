# T3 Desk UI v2: specification (PROPOSAL, not yet approved)

Status: APPROVED by Viet on 9 Oct 2026 (chose "Full UI v2 spec" when asked) and built; the section 11 proposals below stand as written. What differs in the build is listed in `STATUS.md` under Departures. It does not replace `docs/REQUIREMENTS.md`.
Every place it departs from that document is listed in section 11 and needs Viet's approval before coding.
Mockup: `docs/mockups/workspace-4-pane.png` (source `workspace-4-pane.html`).
Not researched with gbrain: see section 12.

## 1. Goals

1. A junior can build a system breakdown and fill every table without a pop-up and without a mouse.
2. The user always sees where they are in the design flow and what to do next, with guidance in plain words.
3. Codes are never shown alone: `N1 - Propulsion`, `R2 - Hunt well`.
4. Notes on any row, written in Markdown, with the author shown.
5. A place for Hermes to assist (search, design suggestions), always through the plugin preview rule.

Non-goals: new business rules, new plugins, deleting anything, AI inside the core app.

## 2. Layout: four panes

One window, four panes left to right, plus a status bar (project, user, Teable state, drafts) and a top bar with Commit.

| Pane | Content |
| --- | --- |
| 1 Menu and decision tree | Screen list with counts; under it the decision tree for the user's role as a checklist (steps done ticked, "Bạn đang ở đây", guidance for the current step, glossary) |
| 2 Breakdown chart | Indented system tree N0 / N1 / N1.1 with status dot, owner, next action, cost roll-up; gate switches; add child; rejected-option nodes greyed |
| 3 Table | Excel-style inline-edit table for the selected node or screen, with tabs (Phân bổ, Thông số, Ứng viên, Đối chiếu, Mua hàng) |
| 4 Context, notes, Hermes | Requirement text and criterion, allocations, check results, row warnings, how-to-fill help, notes thread and composer, Hermes placeholder |

Screens without a hierarchy (Yêu cầu, Kiến trúc, Mua hàng, RFQ, Mốc và quyết định, Bản nháp và Commit) use pane 2 as a list with filter and pane 3 as the table. Pane widths are resizable by keyboard; pane 1 can be narrowed to a strip but never closed (REQUIREMENTS section 6).

## 3. Inline editing (replaces the "Thêm" pop-up)

- Every table is a grid: arrow keys move, typing or `F2` edits, Enter commits the cell, Esc cancels it.
- Typing in the last empty row creates a record. The ID is proposed by `/api/next_id` and shown greyed in the first cell.
- Reference cells (`ma_nut`, `ma_yc`, `ma_uv`, `ma_kt`, `ma_ts`) open a filterable drop-down listing `code - name`; typing filters by either. Multi-value cells (`;`) show chips.
- Choice cells open a drop-down of the schema choices. Numbers accept only numbers; dates use `YYYY-MM-DD`.
- A cell edit becomes a draft on commit of the cell (same `/api/draft` calls as today; create drafts are re-saved whole with `draft_id`, committed records send changed fields only with `base_modified`, so the stale check still works).
- Validation runs per cell and per row; the reason shows under the table and in the cell tooltip. A row with an error stays a draft and blocks Commit with a message naming the row.
- Draft rows: yellow, marked, never silent. Records of a committed row show who changed them when Teable data is newer than the draft base (existing stale flow, shown inline as a two-column cell choice).
- Only one dialog remains: confirm discard of a draft, and the architecture choice reason (open question 2).

Fields come from `schema.yaml`; no field name is hard-coded in the UI.

## 4. Breakdown chart (pane 2)

- Rows: code, name, level, owner, status dot, next action. Dot colour: green Xong, yellow in progress, red warning or waiting for sourcing, grey inactive.
- Selecting a node filters pane 3 and the Designer tree (`node` query) and sets pane 4 context.
- Add child proposes `N0` for an empty tree, `N1` under the root, `N1.1` under N1; the child form is the new row in pane 3 with `ma_cha` prefilled.
- Gates (`chot_cap_1`, `chot_cap_2`) are switches at the top, enabled for the System designer only.
- Nodes tagged `ma_kt` of a rejected architecture and their descendants are greyed and excluded from counters and tasks (already implemented in `rules.py`).

## 5. Decision tree and guidance (pane 1)

- Same `decision_tree.yaml`, three tabs, drawn compactly as a checklist for the pane width; the SVG diagram stays available as a larger view (F1).
- Each question has `help`; the glossary comes from the `guide:` list in the same file (implemented). Guidance text for the current step is shown directly under the highlighted step and mentions the shortcut or table to use.
- The tree highlights the true path for the selected node exactly as now (REQUIREMENTS section 6).

## 6. Notes (pane 4)

- A note belongs to one record (`bang`, `ma_ban_ghi`). Pane 4 lists the notes of the selected row, newest last, with author, time and "đã sửa".
- Composer shows "Người viết: <current user>" from settings; Markdown with Compose and Preview tabs and a small toolbar. Supported Markdown: headings, bold, italic, inline code, code blocks, lists, links, tables. HTML is escaped; links open only after explicit action; no external images.
- Saving a note creates a draft that goes through validation and Commit like any record. A note can be edited only by its author (status `Đã sửa`, text replaced; Teable history keeps the old versions). A note is retired by status `Hủy`, never deleted.
- Storage: new table `ghi_chu` (open question 3). Fields: `ma_gc` (GC-001), `bang`, `ma_ban_ghi`, `nguoi_viet`, `noi_dung` (long text, Markdown), `trang_thai` (Mở / Đã sửa / Hủy). ID field unique and notNull like every ID.
- A row with notes shows a count badge in pane 3 and pane 2. Plain notes do not change rules, counters or next actions.

## 7. Hermes assistant (pane 4, placeholder)

- Version 1 of the placeholder: a panel with disabled actions "Tìm ứng viên", "Gợi ý thông số", "Tra cứu bối cảnh" and an ask box, showing "chưa kết nối" until a plugin supplies actions for the screen (`nut.current`, `thong_so.row`, ...).
- When enabled, actions come from plugin manifests (REQUIREMENTS 9.1). Before any send the app shows the exact payload and the target host; the payload never holds another vendor's price, the budget or scores. Every send is written to the audit log.
- Results are shown in the panel as text; the user can turn a suggestion into a draft by hand ("Tạo dòng nháp từ gợi ý"), via `api.draft_create`. Nothing is written or committed by the assistant.
- Depends on Hermes API details still UNVERIFIED (`docs/reference/`); the placeholder carries no invented endpoint.

## 8. Keyboard model (zero mouse dependency)

Principles: every action reachable by keyboard; visible focus ring; Tab order follows reading order inside a pane; no focus traps; Esc closes overlays and restores focus.

| Group | Keys |
| --- | --- |
| Panes | `Alt+1..4` jump; `F6` / `Shift+F6` next/previous pane; `F1` widen tree |
| Sections | `Ctrl+K` palette (filter screens, nodes, requirements, candidates); `G` then `R/K/C/P/N/M/D` goes to Yêu cầu / Kiến trúc / Cây / Phân bổ / Nút / Mua hàng / Nháp |
| Chart | arrows move; Right/Left expand/collapse; Enter selects and moves focus to table; `Ctrl+Shift+N` add child; Space toggles a gate |
| Table | arrows, Tab/Shift+Tab move cell; `F2` edit; Enter commits cell and moves down; Esc cancels; `Ctrl+D` copy from above; `Ctrl+Shift+Enter` new row; `Ctrl+PageUp/Down` tabs; `Alt+Backspace` discard draft (confirm) |
| Notes and Hermes | `N` focus note box; `Ctrl+Enter` in it saves the note; `Alt+P` preview; `Alt+H` Hermes |
| Global | `Ctrl/Cmd+S` save draft; `Ctrl/Cmd+Enter` Commit; `?` cheat-sheet |

Conflict to resolve: `Ctrl+Enter` is Commit globally (REQUIREMENTS section 8) but saves the note inside the note box; the note box shortcut applies only while it has focus.

## 9. Visual style

Plain CSS tokens in `style.css`: dark and light themes, rounded panes with gaps, accent border on the focused pane, subtle transitions, no fonts or scripts from the network. No framework or build step (CLAUDE.md stack). Electron, Hyprland and Quickshell are not part of this spec (section 11).

## 10. Acceptance tests (to write first, then code)

1. Pane layout: four panes exist, pane 1 holds both the menu and the tree, Alt+1..4 focus them in order (UI file test plus a manual checklist).
2. Inline add: a new row in each table posts exactly the draft bodies of `tests/test_flow_predator.py`; no `modal-root` dialog is created for adding or editing records.
3. Reference cell lists `code - name` for nut, yeu_cau, ung_vien, thong_so, kien_truc, moc (server names payload exists).
4. Keyboard coverage: every shortcut in section 8 is registered and labelled; every clickable element is focusable (static check of `app.js`).
5. Notes: create, edit by author only, refused edit by another user, retire by status, Markdown escaped (`<script>` text is shown, not run), draft goes through Commit, two users' notes get unique IDs.
6. Hermes placeholder: disabled with no plugin; with the fake Hermes plugin, the preview shows payload and host, payload has no price, budget or score.
7. The existing 460-plus tests and the predator flow test still pass; `scripts/smoke.py` passes.
8. Manual: tab through all four panes without the mouse, on Windows, macOS and Ubuntu.

## 11. Departures and decisions needed from Viet

1. Four-pane layout replaces the left navigation, working area and right tree panel of REQUIREMENTS section 8 (three fixed parts). Needs approval.
2. Inline editing replaces forms and dialogs ("Thêm"); decision on the architecture choice reason: dialog or inline cell.
3. New table `ghi_chu` (15 tables; acceptance test 1 and REQUIREMENTS section 4 change). Alternatives rejected: per-machine SQLite notes (not shared), one note column per table (no thread).
4. Notes rendered as Markdown by a built-in minimal renderer (no library allowed).
5. Hermes assistant is a placeholder only; real behaviour waits for the Hermes API reference and the LAN-data decision (REQUIREMENTS section 13).
6. Stack stays Python plus pywebview and plain HTML/CSS/JS. The request for Electron, Hyprland and Quickshell conflicts with CLAUDE.md, section 3 (Electron rejected), the 80 MB / 200 MB limits and the Windows/macOS/Ubuntu requirement, and Hyprland and Quickshell are Linux-only. Not included until decided.
7. Is pane 4 the context, notes and Hermes pane, and do all screens move to this layout or only system design and node work?

## 12. Research note

The user asked for research through gbrain. It was not done: no gbrain tool is available in this session, and CLAUDE.md and STATUS.md say never to run against a real gbrain (the adapter is read-only and UNVERIFIED). This spec comes from the repository, the requirements, the flow test findings and the user's requests. If Viet wants gbrain context (for example prior notes on design-tool UX), run the `mcp_tool` "Tra cứu bối cảnh" action from a machine that is set up for it and add results here.
