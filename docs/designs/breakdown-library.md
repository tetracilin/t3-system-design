# Design: reusable library and a breakdown with alternatives

Branch: `feature/breakdown-library` · 9 Oct 2026 · Status: pass 1 built, pass 2 planned · Decisions by Viet in chat.

## Problem

The system breakdown was one hierarchy of `nut` rows (N0, N1, N1.1), each typed in by hand. In real projects the same
sub-system or OEM part appears in several architectures, juniors are asked to describe many such parts in detail, and
nobody can choose an architecture before the sub-systems, components and RFQs are looked at. The team works through
six steps, many times, with several people: (1) identify architecture, (2) break down, (3) attribute requirements,
(4) match specifications, (5) RFQ or RFP, (6) choose.

## Decisions (asked 9 Oct 2026, all four taken as recommended)

| Question | Choice | Why |
| --- | --- | --- |
| Data model | **Library + placement**: new table `hang_muc` (library item); `nut` stays the placement in an architecture and gets `ma_hm` | Every rule, spec, allocation, candidate, RFQ and ~13 test files already point at `nut`; nothing there changes |
| Where alternatives live | **At every slot** (decision tree) | Matches the six-step loop; the architecture is just the first level of choice |
| Library scope | **Per project base** | No second Teable base or token; items can be imported from another project later |
| Delivery | **Pass 1 now, pass 2 next** | The library can be tried with a junior before the tree is redrawn |

## Pass 1: what is built

- **`hang_muc` (library item)**, ID `HM-001`: `ten`, `cap` (Hệ thống / Hệ con / Linh kiện), `loai` (kind, same list as `nut.loai`),
  `chuc_nang`, OEM data `hang`, `model`, `sku`, `link_datasheet`, `trang_thai` (Chỗ giữ chỗ / Đang điền / Đã điền / Ngưng dùng),
  `nguoi_dien` (who fills it), `ghi_chu`. Nothing is deleted: an item is retired with `Ngưng dùng`.
- **`nut.ma_hm`**: the item placed at this node. The analysis layer (`rules.Analysis`) merges the item's name, function and
  kind into the node, so everything downstream (chart, RFQ payload, tasks, minimum candidates) uses the library values and an
  edit to the item shows in every place it is used. `nut.ten` and `nut.loai` are no longer required; a node with neither a
  name nor an item gets the warning `node_no_name`.
- **Three levels, clear labels**: level 0 = System, 1 = Sub-system, 2 = Component (chips in the chart). An OEM part with a
  SKU can sit at level 1 or 2; the item's `cap` is a hint, not a constraint.
- **Reuse**: library panel under the chart (search by code, name, maker, model, SKU; "mine" filter). Add an item to the
  selected node with the button or Enter, or drag it onto a node or an architecture header. Nothing is copied.
- **Quick placeholder**: type a name (and who fills it) and press Enter: the library item is created as `Chỗ giữ chỗ`
  and placed in one step; Shift+Enter creates it in the library only. Warning `lib_unassigned` if nobody is assigned,
  `lib_oem_incomplete` if an OEM item is marked done without maker and model or SKU.
- **Library screen** (`thu_vien`): every item in an editable table, "Dùng" adds it to the breakdown; "Hạng mục thư viện
  cần điền" lists the items given to the current user on Tổng quan.
- **Architecture scaffold**: "Tạo khung" on an architecture reads its `he_con_cap1` (names separated by `;` or new lines)
  and creates a placeholder sub-system for each, reusing a library item of the same name; the root System is made when the
  project has none. Safe to repeat. Placements are tagged with the architecture (`nut.ma_kt`), which already deactivates
  them when the architecture is rejected.
- **Chart as branches**: under the System, one branch per architecture (with its state and a "Tạo khung" button) and a
  "Chung" branch for nodes common to all; a selector shows one architecture at a time.
- **ID with name** everywhere: chart, grids, lists, warnings, drafts, notes titles, matrices.

## Pass 2: planned, not built

1. **Alternatives at a slot**: a slot (a place under a parent) can hold several candidate items until one is chosen;
   counters and next actions ignore unchosen branches (a generalisation of `_inactive_nodes`). New fields on `nut`
   (slot and chosen flag) are a schema change: ask first.
2. **Stage board** for the six steps per architecture, who works on what, and what blocks the choice (for example RFQs
   sent but unanswered).
3. **Decision-tree drawing** of the breakdown (today it is an indented list grouped by architecture).
4. **Assign in bulk** and a "to fill" queue per person; notifications stay out of scope.

## Open questions for Viet

- Should one item be allowed under the same parent twice (quantity) or should the second add increase `so_luong`? Today it
  makes a second place.
- Should specifications of an OEM item (datasheet values) live on the item so they follow it everywhere? This is the
  "full split" option that was not chosen for pass 1.
- Library import from another project: CSV, or a copy command? Not needed until a second project starts.
