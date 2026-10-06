# Flow test: design a PREDATOR (tests/test_flow_predator.py)

What was run: the server API against `tests/fake_teable.py` (and `tests/fake_hermes.py` for RFQs), in the order a
junior team would use the screens. Nothing touched a real server. Part 1 follows steps 1 to 7 of the brief with KT-B
chosen on best scores. Part 2 is the follow-up: specs for every leaf, five RFQs as comparison quotes, quotes
entered, then KT-A chosen and KT-B, KT-C rejected.

## Hard bugs found and fixed

1. **Child of the root got the ID `N0.1`.** The Add child button on N0 asks `/api/next_id?parent=N0`, which proposed
   `N0.1`; that fails the node ID pattern, so the first thing a junior did on the Cây hệ thống screen was refused.
   The first node of an empty tree was also proposed as `N1` (a second root), never `N0`.
   Fix: `schema._next_tree` proposes `N0` for an empty tree and treats the root as "no parent" (`N1`, `N2`, ...).
   Regression: four rows in `tests/test_schema.py::test_next_free_id`, `test_node_id_proposals_follow_the_tree`.
2. Already fixed before this run and now covered end to end: choosing an architecture while it is still a new draft
   (`ma_kt is required`). Covered before and after commit by the two `test_step3_choose_one_architecture_*` tests.

No other hard bug showed up in steps 1 to 7. Everything the UI sends was accepted and committed in dependency order, the
conflict, offline and RFQ paths behaved as in section 5 and 9.

## Gaps that need a decision (not fixed, CLAUDE.md says ask)

1. **Rejected options keep active leaves.** Nodes carry no link to an architecture, so after KT-B and KT-C are `Loại` the
   leaves for fins and wings still count: they show "3. Tìm ứng viên", they count in the counters, and `task_outbox`
   opens `CV|buoc|N1.3` and `CV|buoc|N1.4` for them. Encoded as a strict `xfail`
   (`test_part2_rejected_option_leaves_must_not_have_open_tasks`); it will fail loudly when someone fixes it.
   Options: a `kien_truc` column on `nut` (schema change), derive membership from `he_con_cap1`, or tag by `phuong_an`
   (PA-A to KT-A). Needs Viet. RFQ tasks (`CV|rfq|...`) are not affected: only `Đã gửi` RFQs past their reply date count.
2. **Nodes cannot be retired.** Rule "nothing is deleted, retire by status" has no status field on `nut`; a wrong node
   stays forever. Same question as 1 if a status is added.
3. **Two chosen architectures give no warning.** Section 7 has no such warning. What happens: the decision tree goes back
   to "Chấm 3 điểm, chọn một", leaf next actions say "Chờ chọn kiến trúc". Nothing is shown on the Kiến trúc screen.
4. **Plugins have no UI wiring** (known, in STATUS.md): a junior cannot start an RFQ, see the preview or poll Hermes from
   the app; `commit` does not call `host.after_commit`, so task_outbox only runs when called. The test drives `PluginHost`
   on the app's own store.
5. Only choosing (`Chọn`) is restricted to the System designer. Rejecting an architecture (`Loại`) is open to every role.

## What a first-time user would find confusing, by step

**1 Requirements**
- Errors name the field and the allowed values (`muc 'Rất cần' is not one of Bắt buộc, Mong muốn`), but only in the form
  of the server's English message; the UI maps the code to Vietnamese, the detail stays English.
- `tieu_chi_nghiem_thu` is optional, so a requirement with no acceptance criterion passes and nothing warns later.
- The decision tree says "complete" as soon as every requirement has a level, with no check that the text is meaningful.

**2 Architectures**
- Weighted total uses the cached weights in `cai_dat`; before the first refresh it silently uses equal weights.
- Scores accept only 1 to 5 whole numbers (good), but the message for `4.5` is "must be a whole number" with no hint of range.
- `yc_then_chot` is a `;` list typed by hand; the form shows a hint, no picker.

**3 Choosing**
- The dialog requires a reason, but a second Choose is allowed without telling you the first one is still chosen
  (see gap 3). The Choose button of the others stays enabled.
- A non-System-designer sees the disabled button with a tooltip; a direct call gets `role_required` (403) with the key.

**4 Tree and gates**
- The "new node" button without a parent proposes `N0` or `N1` but does not fill `ma_cha`; a level-1 node saved without a
  parent becomes a second root (warning only on the tree screen). Use Add child.
- Saving a spec before gate 2 is allowed; the warning "Đi sâu quá sớm" shows only on the tree screen, not on the spec form.
- Gate 2 can be switched on with leaves that have no owner; the owner warning appears afterwards.

**5 Allocation, specs, candidates, checks, sourcing**
- A numeric spec with no min and no max saves; the warning is only on the node screen.
- A derived spec (`Dẫn xuất`) does not cover an allocated requirement; the counter "pairs missing spec" moves to 1 and
  the only hint is the warning on the allocation row.
- Rejecting the one failing candidate drops the active count below 3 for a `Mua OEM` node, so the leaf goes back to
  "3. Tìm ứng viên: có 2, cần 3". This is section 7 row 7 working as written, but surprising.
- Entering a candidate with an ID that already exists in Teable (stale cache) is not caught until Commit.
- Candidate status `Chọn` needs a reason and a passing result; the form lets you save it first and warns afterwards.
- The order-by date uses milestone `G4a`; with no milestone no order-by date and no deadline warnings appear.
  With one, a 40-week quote shows "Đã quá hạn đặt hàng" immediately, which is the useful early signal for the decision.

**6 Commit, two users**
- The conflict dialog gives the proposed ID and who took it, and skipped dependents say what they wait for. Good.
- A draft for an ID that exists in the cache is accepted without warning (see above).

**7 Offline**
- Everything works except Commit and Refresh, which say "Teable is not reachable ... commit when it is back". The
  connection state is cached for 5 seconds, so Commit may stay disabled briefly after the server returns.

**RFQ and comparison quotes (part 2)**
- RFQ payloads are built from the cache, not from drafts: the candidate must be committed first, and a candidate without all
  its checks (`Chưa đủ dữ liệu`) needs an extra confirmation.
- One link for all runs in the fake; the real Hermes is UNVERIFIED.
- Quotes arrive in `mua_hang` by hand; the RFQ status is changed by hand (`Đã gửi`, `Đã có trả lời`).
