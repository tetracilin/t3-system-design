"""Section 7 rules and acceptance test 9, on the pressure-tank fixture."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest

from fixtures.pressure_tank import TODAY, Tables, build
from t3desk import rules
from t3desk.rules import Analysis, Context, TEXTS

Mutator = Callable[[Tables], None]


def analyse(t: Tables, **ctx: Any) -> Analysis:
    return Analysis(t, Context(today=TODAY, **ctx))


def row(t: Tables, table: str, field: str, key: str) -> dict[str, Any]:
    return next(r for r in t[table] if r[field] == key)


def codes(a: Analysis) -> set[str]:
    return {w.code for w in a.warnings()}


def keys(a: Analysis, code: str) -> set[str]:
    return {w.key for w in a.warnings() if w.code == code}


def setting(t: Tables, key: str, value: str) -> None:
    row(t, "cai_dat", "khoa", key)["gia_tri"] = value


def add_node(t: Tables, code: str, parent: str | None, owner: str | None = None, kind: str = "Mua OEM") -> None:
    t["nut"].append({"ma_nut": code, "ma_cha": parent, "ten": code, "loai": kind, "so_luong": 1, "phu_trach": owner})


def add_spec(t: Tables, n: int, node: str, yc: str = "R2", **extra: Any) -> None:
    t["thong_so"].append({
        "ma_ts": f"TS-{n:03d}", "ma_nut": node, "ma_yc_goc": yc, "thong_so": "x", "kieu": "Số",
        "gia_tri_min": 1, "muc": "Bắt buộc", **extra,
    })


def add_cand(t: Tables, n: int, node: str, status: str = "Ứng viên", **extra: Any) -> None:
    t["ung_vien"].append({
        "ma_uv": f"UV-{n:03d}", "ma_nut": node, "model": "m", "link_datasheet": "http://x", "ngay_kiem_tra": "2026-10-01",
        "trang_thai": status, "gia_cong_bo": 10, "tien_te": "USD", **({"ly_do": "r"} if status in ("Chọn", "Loại") else {}), **extra,
    })


def add_check(t: Tables, uv: str, ts: str, value: float) -> None:
    t["doi_chieu"].append({"khoa": f"{uv}|{ts}", "ma_uv": uv, "ma_ts": ts, "gia_tri_so": value, "trich_dan": "q", "trang": "1"})


# ------------------------------------------------------------------ texts file

def test_texts_cover_every_row_counter_and_warning() -> None:
    for code in rules.ROW_CODES.values():
        assert "next_" + code in TEXTS
    for name in rules.COUNTER_ORDER:
        assert "counter_" + name in TEXTS
    for code in WARNING_CASES:
        assert "warn_" + code in TEXTS


# ------------------------------------------------------------------ acceptance test 9

def test_acceptance_9_fixture_results() -> None:
    a = analyse(build())
    assert a.next_action("N1.1").text == TEXTS["next_done"] == "Xong"
    digitiser = a.next_action("N1.2")
    assert digitiser.step == 3 and digitiser.row == 7
    assert "có 2, cần 3" in digitiser.text
    expected_counts = {"N2.1": 2, "N2.2": 1, "N3": 1, "N4": 1, "N5": 1}
    for node, count in expected_counts.items():
        action = a.next_action(node)
        assert action.step == 2 and action.row == 4
        assert action.text == f"2. Viết thông số ({count} yêu cầu đã phân bổ)"
    assert a.counters()["pairs_missing_spec"] == 1


def test_fixture_shape_and_baseline_warnings() -> None:
    a = analyse(build())
    assert a.level("N0") == 0
    assert [n for n in a.nodes if a.level(n) == 1] == ["N1", "N2", "N3", "N4", "N5"]
    assert a.leaves == ["N1.1", "N1.2", "N2.1", "N2.2", "N3", "N4", "N5"]
    assert {(w.code, w.key) for w in a.warnings()} == {("alloc_missing_spec", "PB-004")}


def test_levels_and_leaves() -> None:
    t = build()
    add_node(t, "N2.2.1", "N2.2")
    a = analyse(t)
    assert [a.level(c) for c in ("N0", "N1", "N1.1", "N2.2.1")] == [0, 1, 2, 3]
    assert not a.is_leaf("N2.2") and a.is_leaf("N2.2.1")


def test_non_leaf_progress_text() -> None:
    a = analyse(build())
    assert a.progress("N1") == (1, 2)
    assert a.progress_text("N1") == "1/2 nút lá đã xong"
    assert a.progress("N0") == (1, 7)


# ------------------------------------------------------------------ check pass logic

@pytest.mark.parametrize(
    "hand, value, lo, hi, expected",
    [
        ("Đạt", None, 1, 5, rules.PASS),
        ("Đạt", 99, 1, 5, rules.PASS),  # hand overrides the number
        ("Không đạt", 3, 1, 5, rules.FAIL),
        ("Không rõ", 3, 1, 5, rules.UNCHECKED),
        (None, 3, 1, 5, rules.PASS),
        (None, 1, 1, 5, rules.PASS),  # bounds are inclusive
        (None, 5, 1, 5, rules.PASS),
        (None, 0.5, 1, 5, rules.FAIL),
        (None, 5.1, 1, 5, rules.FAIL),
        (None, 100, 1, None, rules.PASS),  # empty bound is no bound
        (None, -100, None, 5, rules.PASS),
        (None, 100, None, None, rules.PASS),
        (None, None, 1, 5, rules.UNCHECKED),  # no value
    ],
)
def test_check_state_numeric(hand: str | None, value: float | None, lo: Any, hi: Any, expected: str) -> None:
    t = build()
    spec = row(t, "thong_so", "ma_ts", "TS-003")
    spec["gia_tri_min"], spec["gia_tri_max"] = lo, hi
    check = {"khoa": "UV-004|TS-003", "ma_uv": "UV-004", "ma_ts": "TS-003"}
    if hand:
        check["danh_gia_tay"] = hand
    if value is not None:
        check["gia_tri_so"] = value
    t["doi_chieu"] = [c for c in t["doi_chieu"] if c["khoa"] != "UV-004|TS-003"] + [check]
    assert analyse(t).check_state("UV-004", "TS-003") == expected


def test_check_state_qualitative_value_alone_is_not_checked() -> None:
    t = build()
    row(t, "thong_so", "ma_ts", "TS-003")["kieu"] = "Định tính"
    assert analyse(t).check_state("UV-004", "TS-003") == rules.UNCHECKED


def test_check_state_missing_row_is_unchecked() -> None:
    assert analyse(build()).check_state("UV-004", "TS-001") == rules.UNCHECKED


# ------------------------------------------------------------------ candidate result

def test_candidate_result_pass() -> None:
    a = analyse(build())
    assert a.candidate_result("UV-001") == rules.RES_PASS
    assert a.result_text("UV-001") == "Đạt"


def test_candidate_result_fails_must_have() -> None:
    t = build()
    row(t, "doi_chieu", "khoa", "UV-001|TS-002")["gia_tri_so"] = 5  # below min 10
    a = analyse(t)
    assert a.candidate_result("UV-001") == rules.RES_FAIL_MUST
    assert a.result_text("UV-001") == "Trượt bắt buộc"


def test_candidate_result_failing_nice_to_have_does_not_fail() -> None:
    t = build()
    row(t, "thong_so", "ma_ts", "TS-002")["muc"] = "Mong muốn"
    row(t, "doi_chieu", "khoa", "UV-001|TS-002")["gia_tri_so"] = 5
    assert analyse(t).candidate_result("UV-001") == rules.RES_PASS


def test_candidate_result_incomplete_when_a_check_is_missing() -> None:
    t = build()
    t["doi_chieu"] = [c for c in t["doi_chieu"] if c["khoa"] != "UV-001|TS-002"]
    a = analyse(t)
    assert a.candidate_result("UV-001") == rules.RES_INCOMPLETE
    assert a.result_text("UV-001") == "Chưa đủ dữ liệu"


def test_candidate_result_fail_wins_over_incomplete() -> None:
    t = build()
    t["doi_chieu"] = [c for c in t["doi_chieu"] if c["khoa"] != "UV-001|TS-002"]
    row(t, "doi_chieu", "khoa", "UV-001|TS-001")["gia_tri_so"] = -300
    assert analyse(t).candidate_result("UV-001") == rules.RES_FAIL_MUST


# ------------------------------------------------------------------ price and cost

def test_price_prefers_quote_and_converts_with_rates() -> None:
    a = analyse(build())
    assert a.price_used("UV-001") == pytest.approx(1200 * 0.025)  # quoted USD
    assert a.price_used("UV-002") == pytest.approx(1000 * 0.025)  # published USD, no quote


def test_price_vnd_and_unknown_currency() -> None:
    t = build()
    row(t, "ung_vien", "ma_uv", "UV-002")["gia_cong_bo"] = 30_000_000
    row(t, "ung_vien", "ma_uv", "UV-002")["tien_te"] = "VND"
    assert analyse(t).price_used("UV-002") == pytest.approx(30.0)
    row(t, "ung_vien", "ma_uv", "UV-002")["tien_te"] = "JPY"
    assert analyse(t).price_used("UV-002") is None
    row(t, "ung_vien", "ma_uv", "UV-002")["gia_cong_bo"] = None
    assert analyse(t).price_used("UV-002") is None


def test_cost_rolls_up_from_chosen_candidates() -> None:
    a = analyse(build())
    assert a.node_cost("N1.1") == pytest.approx(2 * 30.0)  # quantity 2 x 1200 USD
    assert a.node_cost("N1.2") == 0.0  # nothing chosen
    assert a.node_cost("N1") == pytest.approx(60.0)
    assert a.node_cost("N0") == pytest.approx(60.0)


def test_cost_sums_two_leaves() -> None:
    t = build()
    row(t, "ung_vien", "ma_uv", "UV-004")["trang_thai"] = "Chọn"
    row(t, "ung_vien", "ma_uv", "UV-004")["ly_do"] = "r"
    a = analyse(t)
    assert a.node_cost("N1") == pytest.approx(60.0 + 25.0)


# ------------------------------------------------------------------ budget totals

def test_budget_total_adds() -> None:
    b = analyse(build()).budget_totals()["R4"]
    assert (b.total, b.limit, b.margin, b.over, b.method) == (90.0, 100.0, 10.0, False, "Cộng")


def test_budget_total_rss() -> None:
    t = build()
    for r, v in (("PB-006", 30.0), ("PB-007", 40.0)):
        row(t, "phan_bo", "ma_pb", r).update(gia_tri_phan_bo=v, cach_cong="RSS", gioi_han_he_thong=50.0)
    b = analyse(t).budget_totals()["R4"]
    assert b.total == pytest.approx(math.hypot(30, 40)) and not b.over  # exactly the limit


def test_budget_over_counts_rows() -> None:
    t = build()
    row(t, "phan_bo", "ma_pb", "PB-007")["gia_tri_phan_bo"] = 70.0
    a = analyse(t)
    assert a.budget_totals()["R4"].over
    assert a.counters()["budget_rows_over"] == 2


# ------------------------------------------------------------------ next action table (11 rows)

def third_candidate(t: Tables, ok: bool | None) -> None:
    """Add UV-006 on N1.2; ok True = passing check, False = failing check, None = no check."""
    add_cand(t, 6, "N1.2")
    if ok is not None:
        add_check(t, "UV-006", "TS-003", 96 if ok else 10)


def r1_none(t: Tables) -> None:
    row(t, "kien_truc", "ma_kt", "KT-B")["trang_thai"] = "Đề xuất"
    row(t, "kien_truc", "ma_kt", "KT-A")["trang_thai"] = "Đề xuất"


def r1_two(t: Tables) -> None:
    row(t, "kien_truc", "ma_kt", "KT-B")["trang_thai"] = "Chọn"


def r4(t: Tables) -> None:
    t["thong_so"] = [s for s in t["thong_so"] if s["ma_nut"] != "N1.1"]


def r6(t: Tables) -> None:
    row(t, "doi_chieu", "khoa", "UV-001|TS-002")["gia_tri_so"] = 5


def r8(t: Tables) -> None:
    third_candidate(t, None)


def r9(t: Tables) -> None:
    third_candidate(t, False)
    for uv in ("UV-004", "UV-005"):
        row(t, "doi_chieu", "khoa", f"{uv}|TS-003")["gia_tri_so"] = 10


def r10(t: Tables) -> None:
    third_candidate(t, True)


def r11(t: Tables) -> None:
    third_candidate(t, True)
    t["mua_hang"].append({"ma_uv": "UV-004", "don_gia_bao": 5, "tien_te": "USD", "tg_cho_tuan": 3, "tinh_trang_nguon": "Có hàng sẵn"})


NEXT_CASES = [
    (1, r1_none, "N1.2", "Chờ chọn kiến trúc"),
    (1, r1_two, "N1.2", "Chờ chọn kiến trúc"),
    (2, lambda t: setting(t, "chot_cap_1", "Không"), "N1.2", "Chờ chốt cấp 1"),
    (3, lambda t: setting(t, "chot_cap_2", "Không"), "N1.2", "Chờ chốt cấp 2"),
    (4, r4, "N1.1", "2. Viết thông số (2 yêu cầu đã phân bổ)"),
    (5, lambda t: None, "N1.1", "Xong"),
    (6, r6, "N1.1", "Ứng viên đã chọn chưa đạt"),
    (7, lambda t: None, "N1.2", "3. Tìm ứng viên: có 2, cần 3"),
    (8, r8, "N1.2", "4. Đối chiếu datasheet: còn 1 ô"),
    (9, r9, "N1.2", "Không ứng viên nào đạt: báo Thiết kế hệ thống"),
    (10, r10, "N1.2", "Chờ Mua hàng"),
    (11, r11, "N1.2", "5. Chọn một ứng viên, ghi lý do"),
]


@pytest.mark.parametrize("row_no, mutate, node, text", NEXT_CASES, ids=[f"row{c[0]}-{i}" for i, c in enumerate(NEXT_CASES)])
def test_next_action_rows(row_no: int, mutate: Mutator, node: str, text: str) -> None:
    t = build()
    mutate(t)
    action = analyse(t).next_action(node)
    assert (action.row, action.text) == (row_no, text)


def test_next_action_first_match_wins() -> None:
    t = build()
    setting(t, "chot_cap_1", "Không")
    setting(t, "chot_cap_2", "Không")
    r1_none(t)
    assert analyse(t).next_action("N1.1").row == 1
    row(t, "kien_truc", "ma_kt", "KT-A")["trang_thai"] = "Chọn"
    assert analyse(t).next_action("N1.1").row == 2


def test_next_action_minimum_candidates_is_one_for_non_oem() -> None:
    t = build()
    add_spec(t, 4, "N2.1", "R3")
    action = analyse(t).next_action("N2.1")
    assert action.row == 7 and action.text == "3. Tìm ứng viên: có 0, cần 1"


def test_next_action_minimum_comes_from_settings() -> None:
    t = build()
    setting(t, "so_uv_toi_thieu", "2")
    assert analyse(t).next_action("N1.2").row == 10  # 2 candidates are enough; checks done, no quote


def test_rejected_candidate_missing_checks_do_not_count() -> None:
    t = build()
    add_cand(t, 6, "N1.2", "Loại")  # rejected, no checks
    add_cand(t, 7, "N1.2")
    add_check(t, "UV-007", "TS-003", 96)
    action = analyse(t).next_action("N1.2")
    assert action.row == 10  # three live candidates, all checked, none quoted


def test_waiting_for_sourcing_leaf_does_not_count_as_open() -> None:
    t = build()
    r10(t)
    assert analyse(t).next_action("N1.2").row == 10
    assert analyse(t, user="binh").ctx.user == "binh"


# ------------------------------------------------------------------ dashboard counters

def counter_after(mutate: Mutator, name: str) -> int:
    t = build()
    mutate(t)
    return analyse(t).counters()[name]


def test_counter_baseline() -> None:
    assert analyse(build()).counters() == {
        "must_not_allocated": 0, "pairs_missing_spec": 1, "budget_rows_over": 0,
        "passing_not_picked_up": 3, "chosen_no_quote": 0, "chosen_no_lead_time": 0, "rows_with_warning": 1,
    }


def test_counter_must_not_allocated() -> None:
    def drop_r3(t: Tables) -> None:
        t["phan_bo"] = [p for p in t["phan_bo"] if p["ma_yc"] != "R3"]

    assert counter_after(drop_r3, "must_not_allocated") == 1

    def drop_r5(t: Tables) -> None:  # R5 is Mong muốn: not counted
        t["phan_bo"] = [p for p in t["phan_bo"] if p["ma_yc"] != "R5"]

    assert counter_after(drop_r5, "must_not_allocated") == 0


def test_counter_passing_not_picked_up() -> None:
    def quote_uv2(t: Tables) -> None:
        t["mua_hang"].append({"ma_uv": "UV-002", "trang_thai_mua": "Mở"})

    assert counter_after(quote_uv2, "passing_not_picked_up") == 2  # UV-002, UV-004, UV-005 minus UV-002

    def break_uv2(t: Tables) -> None:
        row(t, "doi_chieu", "khoa", "UV-002|TS-002")["gia_tri_so"] = 5

    assert counter_after(break_uv2, "passing_not_picked_up") == 2  # failing candidates do not wait for sourcing


def test_counter_chosen_without_quote_or_lead_time() -> None:
    def clear(t: Tables) -> None:
        t["mua_hang"][0]["don_gia_bao"] = None
        t["mua_hang"][0]["tg_cho_tuan"] = None

    assert counter_after(clear, "chosen_no_quote") == 1
    assert counter_after(clear, "chosen_no_lead_time") == 1

    def drop_row(t: Tables) -> None:
        t["mua_hang"] = []

    assert counter_after(drop_row, "chosen_no_quote") == 1


def test_counter_rows_with_warning_counts_distinct_rows() -> None:
    t = build()
    row(t, "ung_vien", "ma_uv", "UV-002")["link_datasheet"] = ""
    row(t, "ung_vien", "ma_uv", "UV-002")["ngay_kiem_tra"] = ""  # two warnings, one row
    assert analyse(t).counters()["rows_with_warning"] == 2


# ------------------------------------------------------------------ warnings: trigger and near-miss

def t_parent_missing(t: Tables) -> None:
    row(t, "nut", "ma_nut", "N2.2")["ma_cha"] = "N2x"


def n_parent_missing(t: Tables) -> None:
    add_node(t, "N2x", "N0")
    row(t, "nut", "ma_nut", "N2.2")["ma_cha"] = "N2x"


def t_too_deep(t: Tables) -> None:
    add_node(t, "N2.2.1", "N2.2")


def n_too_deep(t: Tables) -> None:
    add_node(t, "N3.1", "N3")


def t_multi_root(t: Tables) -> None:
    add_node(t, "N9", None)


def n_multi_root(t: Tables) -> None:
    add_node(t, "N9", "N0")


def t_bad_parent(t: Tables) -> None:
    row(t, "nut", "ma_nut", "N2.2")["ma_cha"] = "N1"


def n_bad_parent(t: Tables) -> None:
    add_node(t, "N1.3", "N1")


def t_too_early(t: Tables) -> None:
    setting(t, "chot_cap_2", "Không")


def n_too_early(t: Tables) -> None:
    setting(t, "chot_cap_2", "Không")
    for name in ("thong_so", "ung_vien", "doi_chieu"):
        t[name] = []


def t_no_owner(t: Tables) -> None:
    row(t, "nut", "ma_nut", "N3")["phu_trach"] = None


def n_no_owner(t: Tables) -> None:
    setting(t, "chot_cap_2", "Không")  # before the gate an empty owner is fine
    row(t, "nut", "ma_nut", "N3")["phu_trach"] = None


def t_one_node(t: Tables) -> None:
    add_node(t, "N1.3", "N1", "binh")
    add_spec(t, 9, "N1.3")


def n_one_node(t: Tables) -> None:
    add_node(t, "N1.3", "N1", "binh")  # no specification yet: step 2, not step 3/4/5


def n_one_node_waiting(t: Tables) -> None:
    """binh owns N1.2 (step 5) and N1.3 at Chờ Mua hàng: does not count."""
    r11(t)
    add_node(t, "N1.3", "N1", "binh")
    add_spec(t, 9, "N1.3")
    for n in (7, 8, 9):
        add_cand(t, n, "N1.3")
        add_check(t, f"UV-{n:03d}", "TS-009", 5)


def t_arch_few(t: Tables) -> None:
    t["kien_truc"] = t["kien_truc"][:1]


def n_arch_few(t: Tables) -> None:
    t["kien_truc"].append({"ma_kt": "KT-C", "ten": "Ba", "trang_thai": "Đề xuất"})


def t_arch_reason(t: Tables) -> None:
    row(t, "kien_truc", "ma_kt", "KT-B")["ly_do"] = ""


def n_arch_reason(t: Tables) -> None:
    t["kien_truc"].append({"ma_kt": "KT-C", "ten": "Ba", "trang_thai": "Đề xuất"})  # proposed needs no reason


def t_alloc_dup(t: Tables) -> None:
    t["phan_bo"].append({"ma_pb": "PB-012", "ma_yc": "R1", "ma_nut": "N1.1", "kieu": "Mỗi nút phải đạt"})


def n_alloc_dup(t: Tables) -> None:
    t["phan_bo"].append({"ma_pb": "PB-012", "ma_yc": "R1", "ma_nut": "N2.2", "kieu": "Mỗi nút phải đạt"})


def t_alloc_nonleaf(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-011")["kieu"] = "Mỗi nút phải đạt"


def n_alloc_nonleaf(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-011")["kieu"] = "Kiểm ở cấp hệ thống"


def t_budget_incomplete(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-006")["cach_cong"] = ""


def n_budget_incomplete(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-006")["gia_tri_phan_bo"] = 0  # zero is a share


def t_limit_differs(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-007")["gioi_han_he_thong"] = 90.0


def n_limit_differs(t: Tables) -> None:
    for pb in ("PB-006", "PB-007"):
        row(t, "phan_bo", "ma_pb", pb)["gioi_han_he_thong"] = 120.0


def t_over(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-007")["gia_tri_phan_bo"] = 70.0


def n_over(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-007")["gia_tri_phan_bo"] = 60.0  # total equals the limit


def t_single_many(t: Tables) -> None:
    for pb in ("PB-005", "PB-008"):
        row(t, "phan_bo", "ma_pb", pb)["kieu"] = "Một nút gánh"


def n_single_many(t: Tables) -> None:
    row(t, "phan_bo", "ma_pb", "PB-005")["kieu"] = "Một nút gánh"


def t_missing_spec(t: Tables) -> None:
    pass  # the fixture already has the R6 pair on N1.2 without a specification


def n_missing_spec(t: Tables) -> None:
    add_spec(t, 4, "N1.2", "R6")


def t_spec_nobounds(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-001").update(gia_tri_min=None, gia_tri_max=None)


def n_spec_nobounds(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-001").update(gia_tri_min=None, gia_tri_max=0)  # zero is a bound


def t_spec_qual(t: Tables) -> None:
    add_spec(t, 4, "N1.1", "R1", kieu="Định tính", gia_tri_min=None)


def n_spec_qual(t: Tables) -> None:
    add_spec(t, 4, "N1.1", "R1", kieu="Định tính", gia_tri_min=None, mong_doi="kín nước")


def t_spec_level(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["muc"] = ""


def n_spec_level(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["ma_yc_goc"] = "Dẫn xuất"


def t_spec_unknown(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["ma_yc_goc"] = "R99"


def n_spec_unknown(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["ma_yc_goc"] = "Dẫn xuất"


def t_spec_pair(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["ma_yc_goc"] = "R1"  # R1 is not allocated to N1.2


def n_spec_pair(t: Tables) -> None:
    row(t, "thong_so", "ma_ts", "TS-003")["ma_yc_goc"] = "Dẫn xuất"


def t_spec_nonleaf(t: Tables) -> None:
    add_spec(t, 4, "N1")


def n_spec_nonleaf(t: Tables) -> None:
    add_spec(t, 4, "N1.2")


def t_no_datasheet(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002")["link_datasheet"] = ""


def n_no_datasheet(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002")["link_datasheet"] = "http://other"


def t_no_date(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002")["ngay_kiem_tra"] = ""


def n_no_date(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002")["ngay_kiem_tra"] = "2026-10-05"


def t_chosen_failing(t: Tables) -> None:
    row(t, "doi_chieu", "khoa", "UV-001|TS-002")["gia_tri_so"] = 5


def n_chosen_failing(t: Tables) -> None:  # fails a nice-to-have only
    row(t, "thong_so", "ma_ts", "TS-002")["muc"] = "Mong muốn"
    row(t, "doi_chieu", "khoa", "UV-001|TS-002")["gia_tri_so"] = 5


def t_two_chosen(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002").update(trang_thai="Chọn", ly_do="r")


def n_two_chosen(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002").update(trang_thai="Dự phòng")


def t_cand_reason(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-001")["ly_do"] = ""


def n_cand_reason(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-002")["trang_thai"] = "Dự phòng"  # reserve needs no reason


def t_ai(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-001")["nguoi_tim"] = "AI"


def n_ai(t: Tables) -> None:
    row(t, "ung_vien", "ma_uv", "UV-001").update(nguoi_tim="AI", nguoi_kiem_lai="an")
    row(t, "ung_vien", "ma_uv", "UV-002")["nguoi_tim"] = "AI"  # AI, not chosen


def t_too_many(t: Tables) -> None:
    setting(t, "so_uv_toi_da", "1")


def n_too_many(t: Tables) -> None:
    setting(t, "so_uv_toi_da", "2")  # UV-003 is rejected and does not count


def t_mismatch(t: Tables) -> None:
    add_check(t, "UV-004", "TS-001", -170)


def n_mismatch(t: Tables) -> None:
    row(t, "doi_chieu", "khoa", "UV-004|TS-003")["gia_tri_so"] = 100


def t_citation(t: Tables) -> None:
    row(t, "doi_chieu", "khoa", "UV-001|TS-001")["trang"] = ""


def n_citation(t: Tables) -> None:  # no result yet, so no quote is owed
    c = row(t, "doi_chieu", "khoa", "UV-001|TS-001")
    c.update(trang="", trich_dan="", gia_tri_so=None, danh_gia_tay="Không rõ")


def t_rej_open(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-003")["trang_thai_mua"] = "Mở"


def n_rej_open(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-003")["trang_thai_mua"] = "Đóng"


def t_avail(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["tinh_trang_nguon"] = ""


def n_avail(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["tinh_trang_nguon"] = "Hàng về chậm"


def t_lead(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["tg_cho_tuan"] = None


def n_lead(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["tg_cho_tuan"] = 0  # zero weeks is an answer


def t_expired(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["bao_gia_het_han"] = "2026-10-04"


def n_expired(t: Tables) -> None:
    row(t, "mua_hang", "ma_uv", "UV-001")["bao_gia_het_han"] = "2026-10-05"  # valid through today


def milestone(t: Tables, day: str) -> None:
    row(t, "moc", "ma_moc", "G4a")["ngay_du_bao"] = day


def t_order_passed(t: Tables) -> None:
    milestone(t, "2026-10-20")  # minus 4 weeks = 22 Sep


def n_order_passed(t: Tables) -> None:
    milestone(t, "2026-11-02")  # minus 4 weeks = today: not yet passed


def t_order_soon(t: Tables) -> None:
    milestone(t, "2026-11-16")  # minus 4 weeks = today + 14 days


def n_order_soon(t: Tables) -> None:
    milestone(t, "2026-11-17")  # today + 15 days


def t_order_decision(t: Tables) -> None:
    t["quyet_dinh"].append({"ma_qd": "D1", "cau_hoi": "q", "phuc_vu_moc": "G4a", "ngay_du_bao": "2027-03-01"})


def n_order_decision(t: Tables) -> None:
    t["quyet_dinh"].append({"ma_qd": "D1", "cau_hoi": "q", "phuc_vu_moc": "G4a", "ngay_du_bao": "2027-01-15"})


# code -> (trigger, expected keys, near miss)
WARNING_CASES: dict[str, tuple[Mutator, set[str], Mutator]] = {
    "tree_parent_missing": (t_parent_missing, {"N2.2"}, n_parent_missing),
    "tree_too_deep": (t_too_deep, {"N2.2.1"}, n_too_deep),
    "tree_multi_root": (t_multi_root, {"N0", "N9"}, n_multi_root),
    "tree_bad_parent": (t_bad_parent, {"N2.2"}, n_bad_parent),
    "tree_too_early": (t_too_early, {"N1.1", "N1.2"}, n_too_early),
    "tree_leaf_no_owner": (t_no_owner, {"N3"}, n_no_owner),
    "one_node_at_a_time": (t_one_node, {"N1.2", "N1.3"}, n_one_node),
    "arch_too_few": (t_arch_few, {""}, n_arch_few),
    "arch_no_reason": (t_arch_reason, {"KT-B"}, n_arch_reason),
    "alloc_duplicate": (t_alloc_dup, {"PB-001", "PB-012"}, n_alloc_dup),
    "alloc_type_nonleaf": (t_alloc_nonleaf, {"PB-011"}, n_alloc_nonleaf),
    "alloc_budget_incomplete": (t_budget_incomplete, {"PB-006"}, n_budget_incomplete),
    "alloc_limit_differs": (t_limit_differs, {"PB-006", "PB-007"}, n_limit_differs),
    "alloc_budget_over": (t_over, {"PB-006", "PB-007"}, n_over),
    "alloc_single_many": (t_single_many, {"PB-005", "PB-008"}, n_single_many),
    "alloc_missing_spec": (t_missing_spec, {"PB-004"}, n_missing_spec),
    "spec_numeric_no_bounds": (t_spec_nobounds, {"TS-001"}, n_spec_nobounds),
    "spec_qual_no_expected": (t_spec_qual, {"TS-004"}, n_spec_qual),
    "spec_missing_level_or_source": (t_spec_level, {"TS-003"}, n_spec_level),
    "spec_source_unknown": (t_spec_unknown, {"TS-003"}, n_spec_unknown),
    "spec_pair_not_allocated": (t_spec_pair, {"TS-003"}, n_spec_pair),
    "spec_on_nonleaf": (t_spec_nonleaf, {"TS-004"}, n_spec_nonleaf),
    "cand_no_datasheet": (t_no_datasheet, {"UV-002"}, n_no_datasheet),
    "cand_no_date": (t_no_date, {"UV-002"}, n_no_date),
    "cand_chosen_failing": (t_chosen_failing, {"UV-001"}, n_chosen_failing),
    "cand_two_chosen": (t_two_chosen, {"UV-001", "UV-002"}, n_two_chosen),
    "cand_no_reason": (t_cand_reason, {"UV-001"}, n_cand_reason),
    "cand_ai_unchecked": (t_ai, {"UV-001"}, n_ai),
    "cand_too_many": (t_too_many, {"UV-002"}, n_too_many),
    "check_node_mismatch": (t_mismatch, {"UV-004|TS-001"}, n_mismatch),
    "check_no_citation": (t_citation, {"UV-001|TS-001"}, n_citation),
    "src_rejected_open": (t_rej_open, {"UV-003"}, n_rej_open),
    "src_no_availability": (t_avail, {"UV-001"}, n_avail),
    "src_no_lead_time": (t_lead, {"UV-001"}, n_lead),
    "src_quote_expired": (t_expired, {"UV-001"}, n_expired),
    "src_order_passed": (t_order_passed, {"UV-001"}, n_order_passed),
    "src_order_soon": (t_order_soon, {"UV-001"}, n_order_soon),
    "src_order_before_decision": (t_order_decision, {"UV-001"}, n_order_decision),
}


@pytest.mark.parametrize("code", list(WARNING_CASES))
def test_warning_triggers(code: str) -> None:
    trigger, expected_keys, _ = WARNING_CASES[code]
    t = build()
    trigger(t)
    a = analyse(t)
    assert code in codes(a), f"{code} not raised"
    assert expected_keys <= keys(a, code)
    warning = next(w for w in a.warnings() if w.code == code)
    assert warning.text == TEXTS["warn_" + code] and warning.severity == "red"


@pytest.mark.parametrize("code", list(WARNING_CASES))
def test_warning_does_not_trigger_on_near_miss(code: str) -> None:
    _, _, near = WARNING_CASES[code]
    t = build()
    near(t)
    assert code not in codes(analyse(t)), f"{code} raised on its near miss"


def test_warning_cases_cover_every_section_7_code() -> None:
    raised = set(WARNING_CASES)
    for code in raised:
        assert "warn_" + code in TEXTS
    assert len(raised) == len([k for k in TEXTS if k.startswith("warn_")])


def test_waiting_for_sourcing_leaf_not_counted_for_one_node_rule() -> None:
    t = build()
    n_one_node_waiting(t)
    a = analyse(t)
    assert a.next_action("N1.3").row == 10
    assert "one_node_at_a_time" not in codes(a)


def test_warning_owner_is_leaf_owner() -> None:
    t = build()
    t_chosen_failing(t)
    w = next(w for w in analyse(t).warnings() if w.code == "cand_chosen_failing")
    assert (w.owner, w.node) == ("an", "N1.1")


def test_order_by_date() -> None:
    from datetime import date

    a = analyse(build())
    assert a.order_by("UV-001") == date(2027, 2, 1)
    assert a.order_by("UV-002") is None  # no sourcing row, no lead time


def test_sourcing_queue_lists_passing_candidates_without_a_row() -> None:
    assert analyse(build()).sourcing_queue() == ["UV-002", "UV-004", "UV-005"]


# ------------------------------------------------------------------ decision-tree checks

def test_checks_registry_names_in_decision_tree_yaml_exist() -> None:
    import yaml

    data = yaml.safe_load(open(rules.DATA_DIR / "decision_tree.yaml", encoding="utf-8"))
    names = {q["check"] for tree in data.values() for q in tree if "check" in q}
    assert names <= set(rules.CHECKS)


def test_system_checks_on_fixture() -> None:
    a = analyse(build())
    expected = {
        "requirements_complete": True, "two_architectures": True, "one_architecture_chosen": True,
        "gate_level_1": True, "gate_level_2": True, "all_must_allocated": True, "budget_over": False,
        "leaves_assigned": True, "any_node_stuck": False, "counters_zero": False,
    }
    for name, value in expected.items():
        assert rules.run_check(name, a) is value, name


def test_system_checks_negative() -> None:
    t = build()
    t["yeu_cau"][0]["muc"] = ""
    setting(t, "chot_cap_1", "Không")
    t["kien_truc"] = t["kien_truc"][:1]
    assert rules.run_check("requirements_complete", t, Context(today=TODAY)) is False
    assert rules.run_check("gate_level_1", t, Context(today=TODAY)) is False
    assert rules.run_check("two_architectures", t, Context(today=TODAY)) is False
    r9(t)  # irrelevant to the above but exercises any_node_stuck below
    setting(t, "chot_cap_1", "Có")
    row(t, "kien_truc", "ma_kt", "KT-A")["trang_thai"] = "Chọn"
    assert rules.run_check("any_node_stuck", t, Context(today=TODAY)) is True


def test_node_checks_need_a_leaf() -> None:
    a = analyse(build())
    for name in rules.NODE_CHECKS:
        assert rules.run_check(name, a) is None, name
    a_parent = analyse(build(), node="N1")
    for name in rules.NODE_CHECKS:
        assert rules.run_check(name, a_parent) is None, name


def test_node_checks_on_fixture_leaves() -> None:
    hydro = analyse(build(), node="N1.1", user="an")
    assert rules.run_check("node_specs_cover_allocation", hydro) is True
    assert rules.run_check("node_enough_candidates", hydro) is False  # 2 live candidates, OEM needs 3
    assert rules.run_check("node_checks_complete", hydro) is True
    assert rules.run_check("node_has_passing_candidate", hydro) is True
    assert rules.run_check("node_sourcing_answered", hydro) is True
    digi = analyse(build(), node="N1.2", user="binh")
    assert rules.run_check("node_specs_cover_allocation", digi) is False  # R6 has no specification
    assert rules.run_check("node_enough_candidates", digi) is False
    assert rules.run_check("node_sourcing_answered", digi) is False


def test_other_node_open() -> None:
    t = build()
    add_node(t, "N1.3", "N1", "binh")
    add_spec(t, 9, "N1.3")  # binh now owns N1.2 and N1.3, both at step 3
    a = analyse(t, node="N1.2", user="binh")
    assert rules.run_check("other_node_open", a) is True
    assert rules.run_check("other_node_open", analyse(build(), node="N1.2", user="binh")) is False


def test_engineer_checks() -> None:
    t = build()
    t["sai_lech"].append({"ma_sl": "SL-001", "mo_ta": "x", "ma_nut": "N1.2", "nguoi_nhan": "binh", "trang_thai": "Mở"})
    a = analyse(t, user="binh", drafts=2)
    assert rules.run_check("has_drafts", a) is True
    assert rules.run_check("my_change_cards", a) is True
    assert rules.run_check("my_next_actions", a) is True
    assert rules.run_check("my_warnings", a) is True  # PB-004 sits on binh's leaf
    other = analyse(build(), user="an")
    assert rules.run_check("has_drafts", other) is False
    assert rules.run_check("my_change_cards", other) is False
    assert rules.run_check("my_warnings", other) is False
    assert rules.run_check("my_next_actions", other) is False  # an's only leaf is Xong


def test_unknown_check_raises() -> None:
    with pytest.raises(KeyError):
        rules.run_check("nope", build())
