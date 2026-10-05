# Rules area notes: inferences and departures

Files: t3desk/rules.py, t3desk/decision_tree.py, t3desk/data/decision_tree.yaml, `rules:` section appended to labels_vi.yaml,
tests/fixtures/{__init__,pressure_tank}.py, tests/test_rules.py, tests/test_decision_tree.py.

## API
- `rules.Analysis(tables, Context(today, user, node, drafts))`: tables is `{table_key: [flat record dict]}`. Methods: `next_action`, `candidate_result`,
  `check_state`, `price_used`, `node_cost`, `budget_totals`, `counters`, `counters_labeled`, `warnings`, `warnings_for`, `progress_text`, `sourcing_queue`, `order_by`.
- `rules.CHECKS` maps the check names in decision_tree.yaml to functions; `rules.run_check(name, tables_or_analysis, ctx)`. A node check returns None without a leaf node.
- `rules.TEXTS` is the `rules:` section of labels_vi.yaml. Choice values compared by the rules live in `rules.V` (stored data, not UI text).
- `decision_tree.load_trees/TreeStore.reload/evaluate`; YAML 1.1 turns bare `yes`/`no` keys into booleans, the loader maps them back.
- Walk result: `TreeResult(highlighted, steps, leaf)`; leaf has `label` "Bạn đang ở đây". A node check with no leaf node selected gives `highlighted=False` (plain reference).

## Inferences (spec silent)
- Gates are on when the `cai_dat` value is exactly `Có`. Settings read from `cai_dat` rows (`khoa`/`gia_tri`); candidate maximum from `so_uv_toi_da`, minimum from `so_uv_toi_thieu` (3 for Mua OEM, else 1).
- Check state: `Không rõ` is always unchecked, even with a number. `Không đạt` is always fail. A number with a qualitative spec is unchecked.
- Candidate result uses only specifications of the candidate's own node. A failing nice-to-have (Mong muốn) check does not fail the candidate.
- "Candidates" for row 7 (có n) and the maximum rule exclude `Loại`; row 8 counts unchecked cells of non-rejected candidates only (includes `Không rõ`).
- Row 5/6 use the first `Chọn` candidate of the leaf. Step numbers: row 4 = 2, row 7 = 3, row 8 = 4, row 11 = 5 ("one node at a time" uses rows 7, 8, 11).
- Price: quoted price with the `mua_hang.tien_te`, else published price with `ung_vien.tien_te`; empty currency = VND; rates are `ty_gia_<CUR>` (million VND per unit). Unknown currency gives no price (cost 0 for that leaf).
- Leaf cost = `so_luong` (default 1) x price; a leaf with no chosen candidate costs 0; a parent sums leaves only (parent quantity is ignored).
- Budget: only `Chia ngân sách` rows count; method is the first non-empty `cach_cong` of the requirement; limit is the largest limit among its rows; over means total > limit.
  Counter "budget rows over" counts the budget rows of each over-limit requirement.
- Counter "allocation pairs missing a specification" counts pairs on leaves that have at least one specification but none for that requirement, skipping `Kiểm ở cấp hệ thống`
  (otherwise untouched leaves would all count, contradicting test 9 which expects 1). It equals the `alloc_missing_spec` warning rows.
- Counter "passing candidates sourcing has not picked up" = non-rejected candidates with result Đạt and no `mua_hang` row (the Mua hàng "Chờ nhận" queue).
- "Chosen without quote / lead time" look at `mua_hang.don_gia_bao` / `tg_cho_tuan` only (published price does not count as a quote).
- Warnings: all are severity "red". Owner of a warning = `phu_trach` of the node it belongs to. Table-level warning (`arch_too_few`) has key "". "Rows with any warning" counts distinct (table, key).
- `tree_bad_parent`: a code with a dot whose parent is not the code up to the last dot. `tree_too_deep`: level > 2 (three levels at most: N0, N1, N1.1).
- `spec_numeric_no_bounds`: both bounds empty (zero is a bound). `alloc_budget_incomplete`: share, limit or `cach_cong` empty (zero share is fine).
- `alloc_limit_differs`: more than one distinct non-empty limit among all rows of a requirement. `alloc_type_nonleaf`: also applies when the parent is not a leaf and the kind is anything but `Kiểm ở cấp hệ thống`.
- `check_no_citation`: a result is `Đạt`/`Không đạt` or a `gia_tri_so`; it needs both `trich_dan` and `trang`.
- Sourcing: `src_rejected_open` = candidate `Loại` and `trang_thai_mua` is not `Đóng`; rejected candidates get no other sourcing warning. No availability = empty or `Chưa hỏi`.
  Order-by = `G4a` (`ngay_du_bao`, else `ngay_co_so`) minus `tg_cho_tuan` weeks. Passed: before today. Soon: today..today+14 days inclusive. Before decision: order-by earlier than the latest
  `ngay_du_bao` of an unresolved (`ket_luan` empty) decision whose `phuc_vu_moc` is `G4a`.
- Decision-tree checks: `requirements_complete` needs at least one non-Hủy requirement, all with code and level; `one_architecture_chosen` also needs a reason;
  `my_warnings` = any warning owned by the user; `my_next_actions` = an owned leaf at rows 4, 6, 7, 8 or 11; `my_change_cards` = open `sai_lech` for the user;
  `other_node_open` = another owned leaf at rows 7, 8 or 11; `node_specs_cover_allocation` needs at least one spec and one per allocated requirement (system-level pairs excluded).
- Fixture (pressure tank): N3, N4, N5 are level-1 leaves; the four leaves under two nodes are N1.1, N1.2, N2.1, N2.2. Baseline has exactly one warning (PB-004) and counters
  must_not_allocated 0, pairs_missing_spec 1, budget_rows_over 0, passing_not_picked_up 3 (UV-002, UV-004, UV-005), rows_with_warning 1.

## Departures
- None from section 7. The inferences above are the only places the code goes beyond the text.
