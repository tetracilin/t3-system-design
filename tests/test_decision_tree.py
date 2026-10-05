"""Acceptance test 10, logic part: loading, reloading and the highlighted path."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fixtures.pressure_tank import TODAY, build
from t3desk import decision_tree as dt
from t3desk import rules
from t3desk.rules import Context


def ctx(**kw: object) -> Context:
    return Context(today=TODAY, **kw)  # type: ignore[arg-type]


@pytest.fixture
def trees() -> dt.Trees:
    return dt.load_trees()


def test_loads_three_trees_from_the_yaml(trees: dt.Trees) -> None:
    assert set(trees) == {"system_design", "designer", "engineer"}
    assert [len(trees[n]) for n in dt.TREE_NAMES] == [9, 7, 5]
    # YAML 1.1 reads bare yes/no as booleans: they must come back as branches
    last = trees["system_design"][-1]
    assert last.yes and last.no and last.yes.screen == "cay" and last.no.screen == "tong_quan"
    assert trees["designer"][0].yes is None and trees["designer"][0].no.screen is None


def test_system_design_path_on_fixture(trees: dt.Trees) -> None:
    result = dt.evaluate(trees["system_design"], build(), ctx())
    # R/arch/gates/allocation all fine, nothing over budget, leaves assigned, no stuck node
    assert result.highlighted
    assert result.path[:3] == [(0, "yes"), (1, "yes"), (2, "yes")]
    assert result.leaf is not None
    assert (result.leaf.index, result.leaf.answer) == (8, "no")
    assert result.leaf.screen == "tong_quan"
    assert result.leaf.label == "Bạn đang ở đây"


def test_highlight_changes_when_data_changes(trees: dt.Trees) -> None:
    data = build()
    next(r for r in data["cai_dat"] if r["khoa"] == "chot_cap_1")["gia_tri"] = "Không"
    result = dt.evaluate(trees["system_design"], data, ctx())
    assert result.leaf is not None and (result.leaf.index, result.leaf.answer) == (3, "no")
    assert result.leaf.screen == "cay" and "Liệt kê nút cấp 1" in result.leaf.do
    # the walk records every question passed on the way
    assert [s.index for s in result.steps] == [0, 1, 2, 3]
    assert [s.ends_here for s in result.steps] == [False, False, False, True]


def test_yes_branch_is_taken_when_check_is_true(trees: dt.Trees) -> None:
    data = build()
    next(r for r in data["phan_bo"] if r["ma_pb"] == "PB-007")["gia_tri_phan_bo"] = 70.0  # budget over
    result = dt.evaluate(trees["system_design"], data, ctx())
    assert result.leaf is not None and (result.leaf.index, result.leaf.answer) == (6, "yes")
    assert result.leaf.screen == "phan_bo"


def test_missing_branch_means_go_to_next_question(trees: dt.Trees) -> None:
    # question 0 (requirements_complete) has no 'yes' branch, so a true answer moves on
    result = dt.evaluate(trees["system_design"], build(), ctx())
    assert result.steps[0].answer == "yes" and not result.steps[0].ends_here
    # budget_over has no 'no' branch: a false answer moves on to leaves_assigned
    assert (6, "no") in result.path and result.steps[7].index == 7


def test_designer_tree_without_node_is_plain_reference(trees: dt.Trees) -> None:
    result = dt.evaluate(trees["designer"], build(), ctx(user="binh"))
    assert not result.highlighted and result.leaf is None and result.steps == ()


def test_designer_tree_for_non_leaf_is_plain_reference(trees: dt.Trees) -> None:
    result = dt.evaluate(trees["designer"], build(), ctx(user="binh", node="N1"))
    assert not result.highlighted


def test_designer_tree_digitiser_stops_at_candidates(trees: dt.Trees) -> None:
    result = dt.evaluate(trees["designer"], build(), ctx(user="binh", node="N1.2"))
    # gate ok, no other open node, but PB-004's R6 has no specification
    assert result.leaf is not None and (result.leaf.index, result.leaf.answer) == (2, "no")
    assert result.leaf.do.startswith("Viết thông số")


def test_designer_tree_hydrophone_reaches_final_choice(trees: dt.Trees) -> None:
    result = dt.evaluate(trees["designer"], build(), ctx(user="an", node="N1.1"))
    # specs ok; only 2 live candidates for an OEM leaf, so the walk stops at question 3
    assert result.leaf is not None and result.leaf.index == 3 and result.leaf.answer == "no"


def test_designer_tree_waits_for_gate_two(trees: dt.Trees) -> None:
    data = build()
    next(r for r in data["cai_dat"] if r["khoa"] == "chot_cap_2")["gia_tri"] = "Không"
    result = dt.evaluate(trees["designer"], data, ctx(user="an", node="N1.1"))
    assert result.leaf is not None and result.leaf.index == 0 and result.leaf.screen is None


def test_designer_other_node_open_branch(trees: dt.Trees) -> None:
    data = build()
    data["nut"].append({"ma_nut": "N1.3", "ma_cha": "N1", "ten": "x", "loai": "Mua OEM", "phu_trach": "binh"})
    data["thong_so"].append({"ma_ts": "TS-009", "ma_nut": "N1.3", "ma_yc_goc": "R2", "kieu": "Số",
                             "gia_tri_min": 1, "muc": "Bắt buộc", "thong_so": "x"})
    result = dt.evaluate(trees["designer"], data, ctx(user="binh", node="N1.2"))
    assert result.leaf is not None and (result.leaf.index, result.leaf.answer) == (1, "yes")
    assert result.leaf.screen == "nut"


def test_engineer_tree(trees: dt.Trees) -> None:
    drafts = dt.evaluate(trees["engineer"], build(), ctx(user="binh", drafts=3))
    assert drafts.leaf is not None and (drafts.leaf.index, drafts.leaf.answer) == (0, "yes")
    assert drafts.leaf.screen == "commit"
    warned = dt.evaluate(trees["engineer"], build(), ctx(user="binh"))  # PB-004 is on binh's leaf
    assert warned.leaf is not None and warned.leaf.index == 1
    clean = dt.evaluate(trees["engineer"], build(), ctx(user="an"))
    # an: no drafts, no warnings, no change cards, nothing left to do
    assert clean.leaf is not None and (clean.leaf.index, clean.leaf.answer) == (3, "no")


def test_engineer_tree_can_end_without_a_leaf(trees: dt.Trees) -> None:
    data = build()
    # make every counter zero: R6 specified, UV-002/4/5 picked up by sourcing
    data["thong_so"].append({"ma_ts": "TS-004", "ma_nut": "N1.2", "ma_yc_goc": "R6", "kieu": "Số",
                             "gia_tri_min": 1, "muc": "Bắt buộc", "thong_so": "x"})
    for uv in ("UV-004", "UV-005"):
        data["doi_chieu"].append({"khoa": f"{uv}|TS-004", "ma_uv": uv, "ma_ts": "TS-004", "gia_tri_so": 5,
                                  "trich_dan": "q", "trang": "1"})
    for uv in ("UV-002", "UV-004", "UV-005"):
        data["mua_hang"].append({"ma_uv": uv, "trang_thai_mua": "Mở", "tinh_trang_nguon": "Có hàng sẵn", "tg_cho_tuan": 1})
    assert set(rules.Analysis(data, ctx()).counters().values()) == {0}
    # last question has only a 'no' branch; with counters at zero the walk falls off the end
    result = dt.evaluate(trees["engineer"], data, ctx(user="an"))
    assert result.leaf is not None  # 'an' still has the "ask system design for a new node" leaf
    zero = [q for q in trees["engineer"] if q.check == "counters_zero"][0]
    assert rules.run_check(zero.check, data, ctx()) is True


# ------------------------------------------------------------------ loading and reloading

def copy_yaml(tmp_path: Path) -> Path:
    target = tmp_path / "decision_tree.yaml"
    shutil.copy(dt.DEFAULT_PATH, target)
    return target


def test_changing_a_question_and_reloading_changes_the_tree(tmp_path: Path) -> None:
    path = copy_yaml(tmp_path)
    store = dt.TreeStore(path)
    old = store.trees["system_design"][1].q
    path.write_text(path.read_text(encoding="utf-8").replace(old, "Câu hỏi mới?"), encoding="utf-8")
    assert store.trees["system_design"][1].q == old  # not reloaded yet
    store.reload()
    assert store.trees["system_design"][1].q == "Câu hỏi mới?"
    assert store.evaluate("system_design", build(), ctx()).highlighted


def test_unknown_check_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text('x:\n  - q: "?"\n    check: no_such_rule\n', encoding="utf-8")
    with pytest.raises(dt.DecisionTreeError, match="no_such_rule"):
        dt.load_trees(path)


@pytest.mark.parametrize(
    "text",
    ["- just a list\n", "x: []\n", "x:\n  - check: gate_level_1\n", "x:\n  - q: a\n    no: {screen: s}\n", ": : :\n"],
)
def test_malformed_files_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "t.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(dt.DecisionTreeError):
        dt.load_trees(path)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(dt.DecisionTreeError, match="cannot read"):
        dt.load_trees(tmp_path / "nope.yaml")


def test_question_without_check_is_passed_through(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text('x:\n  - q: "plain"\n  - q: "gate"\n    check: gate_level_1\n    yes: {do: "go"}\n', encoding="utf-8")
    trees = dt.load_trees(path)
    result = dt.evaluate(trees["x"], build(), ctx())
    assert result.path == [(0, None), (1, "yes")] and result.leaf is not None and result.leaf.do == "go"


def test_shipped_yaml_text_matches_section_6() -> None:
    trees = dt.load_trees()
    first = trees["system_design"][0]
    assert first.check == "requirements_complete" and first.no.screen == "yeu_cau"
    assert trees["engineer"][-1].check == "counters_zero" and trees["engineer"][-1].yes is None
