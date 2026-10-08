# User test protocol: T3 Desk pilot session

For the first session with one junior on one real project. About 90 minutes. The reviewer watches and does not help
(`docs/designs/review-first-pilot.md`, premise 2). Written in English; the junior sees the Vietnamese UI.

## Before the session (reviewer, 15 minutes)

1. Teable on the NAS is running. The pilot base `bseAYMV8qhuRRpromU8` was bootstrapped on 9 Oct 2026 (15 tables with `ghi_chu`,
   `nut.ma_kt`, the review-cycle setting). A different base needs `t3desk bootstrap` first; it only adds what is missing.
2. On the junior's Windows PC: `run.bat --browser` (or the window build). Khởi tạo: Teable address, the junior's own token,
   name, role Thiết kế hệ thống or Thiết kế nút, "Kiểm tra kết nối", then open the project.
3. Fill in `STATUS.md` "Viet to fill in": junior, project, reviewer, date.
4. Open a text file for the log (below). Screen recording only if the junior agrees.

## Tasks (read them out one at a time; give no hints)

| # | Task | What it tests |
| --- | --- | --- |
| 1 | "Enter the first three requirements of your project." | Typing into the grid, reference-free tables, the draft mark |
| 2 | "Write down two different architectures and choose one." | Choice cells, the reason dialog, the decision tree step |
| 3 | "Build the system breakdown to level 1 and close the gate." | Chart, add child, gate switch (needs System designer) |
| 4 | "Allocate requirement R1 to a node, then write one specification for that node." | Reference drop-down `code - name`, tabs, the "too early" warning |
| 5 | "Add a note to one specification." | Notes in pane 4, author shown |
| 6 | "Send your work to Teable." | Commit screen, failed draft message, conflict if two people use it |
| 7 | "Find what you should do next." | Decision tree checklist, `?` shortcut list, Ctrl+K |
| 8 | "Your architecture has these sub-systems: ... Prepare them for your colleague to fill in." | Library: "Tạo khung", placeholder, assignee, "Hạng mục thư viện cần điền" |
| 9 | "Add a part that another architecture already uses." | Library search, reuse by Enter or drag, "dùng n chỗ" |

Reviewer-only (afterwards): run "Rà soát tuần", write two findings (`QT` = a rule could have caught it, `PĐ` = needed
judgment), end the review, and check the junior sees the findings on "Tổng quan".

## What to watch for (do not answer questions during a task; note them)

- Where the cursor goes after Enter and Tab. Does the junior expect a different place?
- Does the junior click, or use the keyboard? Which shortcuts do they find on their own?
- A red cell or a failed draft at Commit: do they understand the message and fix it unaided?
- Do they notice the decision tree and the "how to fill" text in pane 4, or ignore them?
- Any moment of silence longer than 20 seconds, any "where is...", any wrong guess about what a screen is for.
- Drafts and yellow rows: do they understand that nothing is in Teable until Commit?

## Log (one line per event)

`mm:ss | task | what happened | words the junior used | severity (blocked / slowed / cosmetic)`

## After the session (reviewer, 15 minutes)

1. Tally review findings by `QT` and `PĐ`. After four weekly reviews this decides whether more form-time rules are
   worth building (premise 4).
2. Success criteria of the design: the first real session happens within two weeks; four weekly reviews run in the tool;
   open findings trend down; no spec saved before gate 2 without the warning showing.
3. Record in `STATUS.md` what surprised you, the blocked moments first. Surprises outrank the planned backlog.
4. Ask the junior three questions: What was hardest? What would you do on paper instead? Would you open this tomorrow
   without being asked?

## Known gaps to tell the junior up front

- The Hermes assistant panel is a placeholder and is switched off.
- Retiring a node, editing the architecture reason inline and plugin buttons are not built.
- Only desktop Chrome and the Windows window were considered; ask which they use.
