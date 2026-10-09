# Dogfooding guide: two testers, one real project

For two people who will use T3 Desk for real work from now on: **Tester A, System designer** (role
"Thiết kế hệ thống") and **Tester B, Engineer** (role "Kỹ sư"). You work on the same project at the same time,
on purpose: most of the value (and most of the bugs) is in two people sharing one Teable base.
Written in English; the screens you see are Vietnamese. The one-page Vietnamese quick start is `HUONG_DAN.md`.

The first-session protocol for a watched pilot is `docs/USER-TEST.md`. This guide is for the days after.

## 1. Set up (15 minutes, each tester on their own PC)

1. Get from Viet: the Teable address, **your own** Teable token (never share or reuse a token), and the project
   name. Do not use another person's token; the app records who wrote what.
2. Start the app: `run.bat` (window) or `run.bat --browser`. Use desktop Chrome or the window. A 1920 x 1080
   screen is the design target.
3. Open **Khởi tạo**: enter the Teable address, token, your name and your role (A: Thiết kế hệ thống,
   B: Kỹ sư). Press "Kiểm tra kết nối", then open the project. The top bar must say `Teable: đã kết nối`.
4. Never switch to a different project or base while you have yellow (draft) rows. Drafts are stored on your PC
   per app folder, not per project. Commit or discard first.
5. Press `?` for the shortcut list and `Ctrl+K` to jump to anything by name.

## 2. How the tool works (read once)

- **Draft, then Commit.** Every cell you type is a draft (yellow row, ✎). Nothing is in Teable until you
  open **Bản nháp và Commit** (`Ctrl+Enter`) and press Commit. Red cells name what is wrong; fix them there.
- **First come keeps the ID.** If you and your colleague both take `N7`, the one who commits second
  gets a new ID automatically and sees a message. Nothing already committed is changed.
- **Nothing is deleted.** Retire things by changing the status.
- **Four panes:** menu and the decision-tree checklist ("Bạn đang ở bước nào?"), list or chart, table,
  and context/notes/Hermes. Drag the thin bars between panes to resize them.
- **Decision tree:** the checklist on the left tells you the next step. If it is unclear, that is a finding.
- **Quick add** (button bottom right, `Alt+A`): one pop-up to add a breakdown item, library item, milestone,
  decision, RFQ or RFP. "Lưu và thêm tiếp" keeps it open for the next one.

## 3. The working loop (repeat in iterations; you will go back and forth)

| Step | Screen | Who leads |
| --- | --- | --- |
| 1. Identify architectures | **Kiến trúc**: at least two, with the reason for the choice later | A |
| 2. Break down | **Kiến trúc** (diagram) and **Cây hệ thống** (list and library). "+" on a diagram card adds a child; drag a **Thư viện hạng mục** item onto a card to reuse it. Placeholders are fine: give a name, assign who fills it in | A creates, B fills in details |
| 3. Attribute requirements | **Yêu cầu**, then **Phân bổ**: select a component in the tree first; the tab shows only that component, its children and other places using the same library part. Use the requirement filter | A and B |
| 4. Match specifications | **Nút** tabs: Thông số, Ứng viên, Đối chiếu datasheet; fix the properties of the selected component in the right-hand pane | B |
| 5. RFQ or RFP | **RFQ / RFP** (Quick add has both). Nothing is sent outside; the plugins are placeholders | B drafts, A reviews |
| 6. Choose | Choose the architecture with its reason (**Kiến trúc**, "Chọn kiến trúc này"); close gates 1 and 2 on the system screen. Only the System designer can | A |

Do not decide the architecture before you have tried to identify sub-systems and components and drafted an RFQ.
Going back to step 1 after step 5 is normal and exactly what the tool is for.

## 4. Roles and what each tester should try

**Tester A, System designer**
- Create two architectures for your real project; use "Tạo khung" on one and draw the other in the diagram.
- Build the breakdown to level 2. Create library placeholders and **assign each to Tester B** ("Giao cho ai điền").
- Allocate requirements in Phân bổ; use the filter instead of scrolling the whole matrix.
- Weekly: run **Rà soát tuần**, write findings, end the review.
- Choose the architecture and close the gates when you really would.

**Tester B, Engineer**
- On **Tổng quan** open "Hạng mục thư viện cần điền" and fill in every placeholder assigned to you: make, model,
  SKU, datasheet link, status. Use pane 4 (Thuộc tính) for the selected component.
- Search the library before creating anything; reuse an existing item.
- Write specifications and candidates for your nodes; add notes (`Alt+N`) when something is unclear.
- Draft the RFQ or RFP for the parts you own.

**Both**
- Commit at least once a day, and always before you stop for a long break.
- Each day, work for a while on the *same* node at the same time and commit in turn. This is where conflicts and
  stale-edit messages appear. Say aloud what you see.

## 5. Ground rules

- Use real project data, not made-up data, so the usefulness of the checklists is real.
- If the tool stops you or confuses you, **do not work around it silently.** Write it down (section 6) first.
- Do not edit Teable directly (web UI, API) while dogfooding. The tool must be the only writer.
- Do not paste secrets or tokens into notes or findings.
- The tool does not delete. If something looks wrong, retire it by status and tell Viet.

## 6. Reporting what you find

Keep one shared text file or note per tester. One line per event:

`date time | screen | what I tried | what happened | what I expected | severity`

Severity: **blocked** (could not continue), **slowed** (worked but wasted time), **cosmetic**.
Add a screenshot for anything red or wrong. Send the file to Viet at the end of each week, or immediately for a
blocked item (include the exact error text; the app shows what failed and what to do next).

Also note, in your own words, moments when you reached for a spreadsheet instead, or wished a screen existed.
Those outrank bug reports.

Weekly questions for each tester: What was hardest? What did the tool make easier than the old workbook?
Would you open it tomorrow without being asked?

## 7. Known gaps (do not report these)

- The Hermes assistant panel is a placeholder and switched off. No plugin sends anything outside yet.
- Retiring a node, editing the architecture reason inline and the pass-2 library ideas (alternatives at every slot,
  six-step stage board) are not built.
- Drafts are per app folder, not per project (see section 1, point 4).
- Windows desktop and Chrome only have been tried; tell Viet if you use anything else.

## 8. If something goes wrong

- **Offline or "Teable không kết nối":** keep working; drafts are kept. Commit when the status returns.
- **Commit says a draft failed:** open the row named in the message, fix the red cell, Commit again.
- **Message about a stale edit or duplicate ID:** read it, choose the option it offers, and write the event in your log.
- **App will not start or shows a blank screen:** copy the error text and tell Viet. Do not delete the app folder:
  your drafts are in it.
