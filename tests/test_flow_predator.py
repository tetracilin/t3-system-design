"""A real design project end to end through the server API, as a junior team would use it.

Scenario: design a PREDATOR. R1 "Be an apex predator", R2 "Hunt well". Three architectures:
KT-A legs + eyes + tail (land runner), KT-B fin + sharp teeth + slim body (aquatic hunter),
KT-C wings + eye + beak (aerial hunter).

Every call is one the UI makes (same /api/* routes, same bodies as t3desk/ui/app.js). Plugins
(Hermes RFQ, task outbox) have no UI wiring yet, so those tests drive the PluginHost directly on
the same local store the server uses. Nothing here touches a real server: only tests/fake_teable.py
and tests/fake_hermes.py.

Part 1  steps 1 to 7 of the brief (choose KT-B on best scores).
Part 2  follow-up: specifications for every leaf, RFQs through fake Hermes as comparison quotes for
        all three options, quotes entered, then KT-A chosen and KT-B / KT-C rejected.
Findings for a first-time user: docs/notes/flow-predator.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from fake_hermes import TOKEN, FakeHermes
from fake_teable import FakeTeable
from fixtures.pressure_tank import TODAY
from t3desk import plugins_api as pa
from t3desk import rfq as rfq_mod
from t3desk import server
from t3desk.teable_client import TeableClient
from test_server import Env, env  # noqa: F401  (the env fixture: App wired to the fake Teable)

REPO = Path(__file__).resolve().parent.parent
MUST, WISH = "Bắt buộc", "Mong muốn"
EACH, SYSTEM_LEVEL = "Mỗi nút phải đạt", "Kiểm ở cấp hệ thống"
CHOSEN, PROPOSED, REJECTED = "Chọn", "Đề xuất", "Loại"


# ---- a small "UI" -----------------------------------------------------------------------------


class Flow:
    """The calls the UI makes, one method per user gesture."""

    def __init__(self, env: Env):
        self.env = env
        env.set_identity("an", "system_designer")
        assert env.post("/api/refresh")[0] == 200  # the app refreshes when it starts

    # -- generic
    def save(self, table: str, fields: dict[str, Any], **extra: Any) -> dict[str, Any]:
        status, data = self.env.draft(table, fields, **extra)
        assert status == 200, (table, fields, data)
        return data

    def new_id(self, table: str, **query: str) -> str:
        return self.env.get("/api/next_id", table=table, **query)["id"]

    def add(self, table: str, code: str, fields: dict[str, Any], **query: str) -> dict[str, Any]:
        """New record the way the form does it: take the proposed ID, then save."""
        proposed = self.new_id(table, **query)
        if proposed is not None:  # milestones are free text (G4a): the form proposes nothing
            assert proposed == code, f"the form would propose {proposed}, the scenario uses {code}"
        return self.save(table, {self.env.app.id_names[table]: code, **fields})

    def row(self, table: str, key: str) -> dict[str, Any]:
        return next(r for r in self.env.get("/api/rows", table=table)["rows"] if r["key"] == key)

    def update(self, table: str, key: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Edit a record: a not yet committed one is re-saved whole, a committed one sends the change."""
        row = self.row(table, key)
        if row["draft_op"] == "create":
            return self.save(table, {**row["fields"], **fields}, draft_id=row["draft"])
        # like the form: everything that differs from the Teable values goes into the draft
        desired = {**row["fields"], **fields}
        base = row["base"]
        id_name = self.env.app.id_names[table]
        changed = {k: v for k, v in desired.items()
                   if k != id_name and str(None if v == "" else v) != str(base.get(k))}
        body = {"table": table, "op": "update", "key": key, "record_id": row["record_id"],
                "base_modified": row["modified"], "base_fields": base, "fields": changed}
        if row["draft"]:
            body["draft_id"] = row["draft"]
        status, data = self.env.post("/api/draft", body)
        assert status == 200, (table, key, fields, data)
        return data

    def commit(self) -> dict[str, Any]:
        status, data = self.env.post("/api/commit")
        assert status == 200, data
        assert data["ok"], [r for r in data["results"] if r["status"] != "committed"]
        assert data["drafts"] == 0
        return data

    # -- gestures of particular screens
    def choose(self, key: str, reason: str) -> tuple[int, Any]:
        """Kiến trúc screen, Choose button and the reason dialog (chooseArchitecture in app.js)."""
        card = next(c for c in self.env.get("/api/architectures")["cards"] if c["key"] == key)
        return self.env.post("/api/draft", {
            "table": "kien_truc", "op": "update", "key": key, "record_id": card["record_id"],
            "base_modified": card["modified"], "base_fields": card["fields"], "draft_id": card["draft"] or None,
            "fields": {"trang_thai": CHOSEN, "ly_do": reason}})

    def set_gate(self, key: str, on: bool) -> None:
        """Cây hệ thống screen, the gate switch (setGate in app.js)."""
        text = self.env.get("/api/meta")["values"]["yes" if on else "no"]
        rows = self.env.get("/api/rows", table="cai_dat")["rows"]
        existing = next((r for r in rows if r["key"] == key), None)
        if existing:
            body = {"table": "cai_dat", "op": "update", "key": key, "record_id": existing["record_id"],
                    "base_modified": existing["modified"], "base_fields": existing["base"],
                    "draft_id": existing["draft"], "fields": {"gia_tri": text}}
        else:
            body = {"table": "cai_dat", "op": "create", "fields": {"khoa": key, "gia_tri": text}}
        status, data = self.env.post("/api/draft", body)
        assert status == 200, data

    # -- reading
    def tree_leaf(self, name: str = "system_design", node: str | None = None) -> dict[str, Any]:
        query = {"node": node} if node else {}
        return self.env.get("/api/trees", **query)["trees"][name]["leaf"]

    def node_next(self, code: str) -> str:
        return next(n for n in self.env.get("/api/tree_nodes")["nodes"] if n["code"] == code)["next"]

    def counters(self) -> dict[str, int]:
        return {c["name"]: c["value"] for c in self.env.get("/api/overview")["counters"]}

    def tree_warnings(self, code: str) -> list[str]:
        return next(n for n in self.env.get("/api/tree_nodes")["nodes"] if n["code"] == code)["warnings"]


@pytest.fixture
def flow(env: Env) -> Flow:  # noqa: F811
    return Flow(env)


# ---- scenario data ----------------------------------------------------------------------------


def step1_requirements(f: Flow) -> None:
    f.add("yeu_cau", "R1", {
        "mo_ta": "Be an apex predator", "muc": MUST, "uu_tien": "H", "trang_thai": "Nháp", "nguon": "Customer brief",
        "tieu_chi_nghiem_thu": "No natural predator of the adult animal: zero predation events in 12 months of field survey"})
    f.add("yeu_cau", "R2", {
        "mo_ta": "Hunt well", "muc": MUST, "uu_tien": "H", "trang_thai": "Nháp", "nguon": "Customer brief",
        "tieu_chi_nghiem_thu": "Catch rate of at least 60 % of hunts over 100 observed hunts"})


ARCHS = {
    "KT-A": dict(ten="Land runner", nguyen_ly="Legs, eyes and tail: sprint and turn on land",
                 yc_then_chot="R1;R2", uu_diem="Fast, proven in leopards", nhuoc_diem="Heats up on long chases",
                 rui_ro="Needs open terrain", diem=(4, 3, 4)),
    "KT-B": dict(ten="Aquatic hunter", nguyen_ly="Fin, sharp teeth and a slim body: ambush in water",
                 yc_then_chot="R1;R2", uu_diem="Few predators above it, strong bite", nhuoc_diem="Tied to water",
                 rui_ro="Fin materials are slow to source", diem=(5, 4, 4)),
    "KT-C": dict(ten="Aerial hunter", nguyen_ly="Wings, eye and beak: dive on prey",
                 yc_then_chot="R1;R2", uu_diem="Wide search area", nhuoc_diem="Weight limits the bite",
                 rui_ro="Wing loading", diem=(4, 2, 2)),
}


def step2_architectures(f: Flow) -> None:
    for code, a in ARCHS.items():
        tech, supply, time = a["diem"]
        f.add("kien_truc", code, {
            "ten": a["ten"], "nguyen_ly": a["nguyen_ly"], "yc_then_chot": a["yc_then_chot"], "uu_diem": a["uu_diem"],
            "nhuoc_diem": a["nhuoc_diem"], "rui_ro": a["rui_ro"], "diem_ky_thuat": tech, "diem_nguon_hang": supply,
            "diem_thoi_gian": time, "trang_thai": PROPOSED})


# ====================================================================================================
# Part 1 - the steps of the brief (KT-B chosen)
# ====================================================================================================


def test_step1_requirements_then_decision_tree_says_requirements_complete(flow: Flow) -> None:
    f = flow
    assert f.env.get("/api/state")["default_screen"] == "yeu_cau" and f.env.get("/api/state")["role"] == "system_designer"
    first = f.tree_leaf()
    assert first["index"] == 0 and first["screen"] == "yeu_cau"  # nothing entered: "write the requirements"
    assert f.counters()["must_not_allocated"] == 0

    # the form refuses a requirement without a level and says which field
    status, data = f.env.draft("yeu_cau", {"ma_yc": "R1", "mo_ta": "Be an apex predator", "trang_thai": "Nháp"})
    assert status == 422 and data["error"]["code"] == "invalid"
    assert [i["field"] for i in data["error"]["issues"]] == ["muc"] and data["error"]["issues"][0]["code"] == "required"
    status, data = f.env.draft("yeu_cau", {"ma_yc": "R1", "mo_ta": "x", "muc": "Rất cần", "trang_thai": "Nháp"})
    assert status == 422 and "Bắt buộc" in data["error"]["detail"]  # the message lists the allowed values
    status, data = f.env.draft("yeu_cau", {"ma_yc": "R-1", "mo_ta": "x", "muc": MUST, "trang_thai": "Nháp"})
    assert status == 422 and "R12" in data["error"]["detail"]  # and the ID format with an example
    assert f.env.app.store.count_drafts() == 0

    step1_requirements(f)
    assert f.new_id("yeu_cau") == "R3"  # proposals count the user's own drafts
    rows = {r["key"]: r for r in f.env.get("/api/rows", table="yeu_cau")["rows"]}
    assert set(rows) == {"R1", "R2"} and all(r["draft"] and r["draft_op"] == "create" for r in rows.values())
    assert f.env.get("/api/state")["drafts"] == 2

    tree = f.env.get("/api/trees")["trees"]["system_design"]
    assert tree["steps"][0] == {"index": 0, "answer": "yes", "ends_here": False}  # "requirements complete"
    assert tree["leaf"]["index"] == 1 and tree["leaf"]["screen"] == "kien_truc"  # next: a second architecture
    assert f.counters()["must_not_allocated"] == 2  # both Bắt buộc, no allocation yet


def test_step2_three_architectures_weighted_totals_and_two_architectures_check(flow: Flow) -> None:
    f = flow
    step1_requirements(f)
    assert f.new_id("kien_truc") == "KT-A"
    f.add("kien_truc", "KT-A", {"ten": "Land runner", "trang_thai": PROPOSED, "diem_ky_thuat": 4, "diem_nguon_hang": 3,
                                "diem_thoi_gian": 4})
    assert f.tree_leaf()["index"] == 1  # one architecture is not enough
    assert f.new_id("kien_truc") == "KT-B"

    # scores are 1-5 whole numbers
    status, data = f.env.draft("kien_truc", {"ma_kt": "KT-B", "ten": "x", "trang_thai": PROPOSED, "diem_ky_thuat": 6})
    assert status == 422 and data["error"]["issues"][0]["code"] == "range"
    status, data = f.env.draft("kien_truc", {"ma_kt": "KT-B", "ten": "x", "trang_thai": PROPOSED, "diem_ky_thuat": 4.5})
    assert status == 422 and data["error"]["issues"][0]["code"] == "type"
    status, data = f.env.draft("kien_truc", {"ma_kt": "KT-B", "ten": "x", "trang_thai": PROPOSED, "yc_then_chot": "R9"})
    assert status == 422 and data["error"]["issues"][0]["code"] == "missing_ref"

    for code in ("KT-B", "KT-C"):
        a = ARCHS[code]
        tech, supply, time = a["diem"]
        f.add("kien_truc", code, {"ten": a["ten"], "nguyen_ly": a["nguyen_ly"], "yc_then_chot": a["yc_then_chot"],
                                  "uu_diem": a["uu_diem"], "nhuoc_diem": a["nhuoc_diem"], "rui_ro": a["rui_ro"],
                                  "diem_ky_thuat": tech, "diem_nguon_hang": supply, "diem_thoi_gian": time,
                                  "trang_thai": PROPOSED})
    data = f.env.get("/api/architectures")
    assert data["weights"] == [0.5, 0.3, 0.2]  # the defaults bootstrap wrote to cai_dat
    totals = {c["key"]: c["weighted"] for c in data["cards"]}
    assert totals == {"KT-A": 3.7, "KT-B": 4.5, "KT-C": 3.0}  # 0.5*tech + 0.3*supply + 0.2*time
    assert all(c["draft"] for c in data["cards"]) and data["can_choose"]
    tree = f.env.get("/api/trees")["trees"]["system_design"]
    assert tree["steps"][1]["answer"] == "yes"  # two_architectures is true now
    assert tree["leaf"]["index"] == 2 and tree["leaf"]["do"].startswith("Chấm 3 điểm")  # choose one


def test_step3_choose_one_architecture_before_commit(flow: Flow) -> None:
    """This exact path used to fail with 'ma_kt is required'."""
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    status, data = f.choose("KT-B", "Best weighted score 4.5 against 3.7 and 3.0")
    assert status == 200, data
    draft = data["draft"]
    assert draft["op"] == "create" and draft["valid"] and draft["key"] == "KT-B"
    assert draft["fields"]["ma_kt"] == "KT-B" and draft["fields"]["trang_thai"] == CHOSEN
    assert draft["fields"]["diem_ky_thuat"] == 5 and draft["fields"]["ten"] == "Aquatic hunter"  # nothing was lost
    assert f.env.app.store.count_drafts() == 5  # R1 R2 + three architectures: still one draft per record
    cards = f.env.get("/api/architectures")["cards"]
    assert [c["key"] for c in cards if c["fields"]["trang_thai"] == CHOSEN] == ["KT-B"]
    assert f.tree_leaf()["index"] == 3 and f.tree_leaf()["screen"] == "cay"  # one chosen with a reason: tree is next

    # a second choice: the app accepts it (two drafts say Chọn) and the tree goes back to "choose one"
    status, data = f.choose("KT-C", "I also like wings")
    assert status == 200
    chosen = [c["key"] for c in f.env.get("/api/architectures")["cards"] if c["fields"]["trang_thai"] == CHOSEN]
    assert chosen == ["KT-B", "KT-C"]
    assert f.tree_leaf()["index"] == 2  # one_architecture_chosen is false again
    f.update("kien_truc", "KT-C", {"trang_thai": PROPOSED})  # undo it with the edit form
    assert [c["key"] for c in f.env.get("/api/architectures")["cards"] if c["fields"]["trang_thai"] == CHOSEN] == ["KT-B"]

    f.commit()
    stored = {r["fields"]["ma_kt"]: r["fields"] for r in f.env.fake.records("kien_truc")}
    assert [k for k, v in stored.items() if v["trang_thai"] == CHOSEN] == ["KT-B"]
    assert stored["KT-B"]["ly_do"].startswith("Best weighted score") and stored["KT-C"]["trang_thai"] == PROPOSED


def test_step3_choose_one_architecture_after_commit_is_an_update(flow: Flow) -> None:
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    f.commit()
    assert f.tree_leaf()["index"] == 2
    status, data = f.choose("KT-B", "Best weighted score 4.5 against 3.7 and 3.0")
    assert status == 200, data
    assert data["draft"]["op"] == "update" and data["draft"]["record_id"]
    assert data["draft"]["fields"] == {"trang_thai": CHOSEN, "ly_do": "Best weighted score 4.5 against 3.7 and 3.0"}
    # editing the reason again extends the same draft rather than adding a second one
    f.update("kien_truc", "KT-B", {"ly_do": "Best weighted score 4.5 against 3.7 and 3.0; fewest predators"})
    assert f.env.app.store.count_drafts() == 1
    f.commit()
    chosen = [r["fields"] for r in f.env.fake.records("kien_truc") if r["fields"]["trang_thai"] == CHOSEN]
    assert len(chosen) == 1 and chosen[0]["ma_kt"] == "KT-B" and chosen[0]["ly_do"].endswith("fewest predators")
    # a second architecture marked Chọn after commit: allowed, but nothing counts as chosen any more
    f.choose("KT-A", "second thoughts")
    assert f.tree_leaf()["index"] == 2
    f.update("kien_truc", "KT-A", {"trang_thai": PROPOSED})  # undo with the edit form
    assert f.tree_leaf()["index"] == 3


@pytest.mark.parametrize("role", ["designer", "engineer", "sourcing", "pm"])
def test_step3_only_the_system_designer_can_choose(flow: Flow, role: str) -> None:
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    f.commit()
    f.env.set_identity("binh", role)
    assert f.env.get("/api/architectures")["can_choose"] is False  # the button is disabled
    status, data = f.choose("KT-B", "I pick this")
    assert status == 403 and data["error"]["code"] == "role_required"
    assert f.env.app.store.count_drafts() == 0
    status, data = f.env.post("/api/draft", {"table": "cai_dat", "op": "create", "fields": {"khoa": "chot_cap_1", "gia_tri": "Có"}})
    assert status == 403


def test_step4_system_tree_gates_and_premature_depth_warning(flow: Flow) -> None:
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    assert f.choose("KT-B", "Best weighted score")[0] == 200
    build_kt_b_tree(f, with_gates=False)
    nodes = {n["code"]: n for n in f.env.get("/api/tree_nodes")["nodes"]}
    assert [n for n in nodes if nodes[n]["level"] == 0] == ["N0"]
    assert [nodes[c]["level"] for c in ("N1", "N1.1", "N3.2")] == [1, 2, 2]
    assert nodes["N1.1"]["leaf"] and not nodes["N1"]["leaf"] and nodes["N1"]["next"] == "0/2 nút lá đã xong"
    assert nodes["N3.1"]["next"] == "Chờ chốt cấp 1"  # gate 1 first
    assert f.env.get("/api/tree_nodes")["gates"] == {"chot_cap_1": False, "chot_cap_2": False}

    f.set_gate("chot_cap_1", True)
    assert f.env.get("/api/tree_nodes")["gates"]["chot_cap_1"] is True
    assert f.node_next("N3.1") == "Chờ chốt cấp 2"
    assert f.tree_leaf()["index"] == 4  # level 2 questions next

    # specifications before gate 2: the app lets you save, then warns on the node
    f.add("phan_bo", "PB-001", {"ma_yc": "R2", "ma_nut": "N3.1", "kieu": EACH})
    f.add("thong_so", "TS-001", {"ma_nut": "N3.1", "ma_yc_goc": "R2", "thong_so": "Bite force", "kieu": "Số",
                                 "gia_tri_min": 1500, "don_vi": "N", "muc": MUST})
    assert any("Đi sâu quá sớm" in w for w in f.tree_warnings("N3.1"))
    assert f.node_next("N3.1") == "Chờ chốt cấp 2"  # and the next action still says wait

    f.set_gate("chot_cap_2", True)
    assert not any("Đi sâu quá sớm" in w for w in f.tree_warnings("N3.1"))
    assert f.node_next("N3.1") == "3. Tìm ứng viên: có 0, cần 3"  # the spec is there, so step 3
    assert f.node_next("N1.1") == "2. Viết thông số (0 yêu cầu đã phân bổ)"
    assert f.env.get("/api/tree_nodes")["gates"] == {"chot_cap_1": True, "chot_cap_2": True}
    assert f.tree_leaf()["index"] == 5  # all-must-allocated is next (R1 is not allocated)


def test_node_id_proposals_follow_the_tree(flow: Flow) -> None:
    f = flow
    assert f.new_id("nut") == "N0"  # an empty tree starts with the root
    f.add("nut", "N0", {"ten": "Predator", "loai": "Hệ thống", "so_luong": 1})
    assert f.new_id("nut", parent="N0") == "N1"  # a child of the root is N1, never "N0.1"
    f.add("nut", "N1", {"ma_cha": "N0", "ten": "Propulsion", "loai": "Cụm", "so_luong": 1}, parent="N0")
    assert f.new_id("nut", parent="N0") == "N2"
    assert f.new_id("nut", parent="N1") == "N1.1"


def build_kt_b_tree(f: Flow, *, with_gates: bool = True) -> None:
    """Root, three level-1 nodes and the leaves of the aquatic hunter."""
    f.add("nut", "N0", {"ten": "Predator", "loai": "Hệ thống", "so_luong": 1})
    for code, name in (("N1", "Propulsion (fin/tail)"), ("N2", "Sensing"), ("N3", "Bite system")):
        f.add("nut", code, {"ma_cha": "N0", "ten": name, "loai": "Cụm", "so_luong": 1}, parent="N0")
    leaves = [("N1", "Fin", "chi"), ("N1", "Slim body", "chi"), ("N2", "Lateral line", "dung"),
              ("N3", "Sharp teeth", "binh"), ("N3", "Jaw muscle", "dung")]
    count: dict[str, int] = {}
    for parent, name, owner in leaves:
        count[parent] = count.get(parent, 0) + 1
        code = f"{parent}.{count[parent]}"
        f.add("nut", code, {"ma_cha": parent, "ten": name, "loai": "Mua OEM", "so_luong": 1, "phu_trach": owner},
              parent=parent)
    if with_gates:
        f.set_gate("chot_cap_1", True)
        f.set_gate("chot_cap_2", True)


def test_step5_allocation_specs_candidates_checks_sourcing_choice_with_next_actions(flow: Flow) -> None:
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    assert f.choose("KT-B", "Best weighted score 4.5 against 3.7 and 3.0")[0] == 200
    build_kt_b_tree(f)
    leaf = "N3.1"
    assert f.node_next(leaf) == "2. Viết thông số (0 yêu cầu đã phân bổ)"
    assert f.counters()["must_not_allocated"] == 2

    # allocation: R1 is checked on the whole system, R2 must be met by the teeth
    f.add("phan_bo", "PB-001", {"ma_yc": "R1", "ma_nut": "N0", "kieu": SYSTEM_LEVEL,
                                "cach_kiem_he_thong": "12-month field survey"})
    f.add("phan_bo", "PB-002", {"ma_yc": "R2", "ma_nut": leaf, "kieu": EACH})
    assert f.counters()["must_not_allocated"] == 0
    assert f.node_next(leaf) == "2. Viết thông số (1 yêu cầu đã phân bổ)"
    alloc = f.env.get("/api/alloc")
    assert alloc["cells"]["R2|N3.1"]["key"] == "PB-002" and alloc["cells"]["R1|N0"]["kieu"] == SYSTEM_LEVEL
    assert f.tree_leaf()["index"] == 8  # every leaf has an owner: nothing stuck, compare options at the weekly review

    # the designer now works the leaf
    f.env.set_identity("binh", "designer")
    assert f.env.get("/api/state")["default_screen"] == "nut" and f.env.get("/api/state")["tree"] == "designer"
    assert [x["code"] for x in f.env.get("/api/overview")["leaves"]] == [leaf]
    assert f.tree_leaf("designer", leaf)["index"] == 2 and f.tree_leaf("designer", leaf)["do"].startswith("Viết thông số")

    # a derived spec first: R2 is allocated but not covered, so the counter moves to 1
    f.add("thong_so", "TS-001", {"ma_nut": leaf, "ma_yc_goc": "Dẫn xuất", "thong_so": "Bite force", "kieu": "Số",
                                 "gia_tri_min": 1500, "don_vi": "N", "muc": MUST, "kiem_chung": "Bite rig test"})
    assert f.node_next(leaf) == "3. Tìm ứng viên: có 0, cần 3"
    assert f.counters()["pairs_missing_spec"] == 1
    assert f.row("phan_bo", "PB-002")["warnings"] == ["Nút đã có thông số nhưng không có thông số cho yêu cầu này"]
    f.add("thong_so", "TS-002", {"ma_nut": leaf, "ma_yc_goc": "R2", "thong_so": "Penetration depth", "kieu": "Số",
                                 "gia_tri_min": 20, "gia_tri_max": 60, "don_vi": "mm", "muc": MUST})
    assert f.counters()["pairs_missing_spec"] == 0

    # a numeric spec with neither bound is saved but flagged on the node screen (the form does not stop it)
    status, _ = f.env.draft("thong_so", {"ma_ts": "TS-003", "ma_nut": leaf, "ma_yc_goc": "R2", "thong_so": "x",
                                         "kieu": "Số", "muc": MUST})
    assert status == 200  # saved, but flagged:
    assert f.env.get("/api/node", code=leaf)["specs"][-1]["_warnings"] == ["Thông số số thiếu cả min lẫn max"]
    f.env.post("/api/draft/discard", {"draft_id": f.row("thong_so", "TS-003")["draft"]})

    # three candidates with datasheet link and check date
    teeth = [("UV-001", "Great white set", 1000.0), ("UV-002", "Tiger shark set", 800.0), ("UV-003", "Barracuda set", 300.0)]
    for i, (code, model, price) in enumerate(teeth, 1):
        f.add("ung_vien", code, {"ma_nut": leaf, "hang": "Reef Dental", "model": model, "cau_hinh": "serrated",
                                 "xuat_xu": "VN", "gia_cong_bo": price, "tien_te": "USD", "loai_gia": "Giá công bố",
                                 "link_datasheet": f"http://ds.invalid/{code}", "ngay_kiem_tra": "2026-10-05",
                                 "nguoi_tim": "Người", "trang_thai": "Ứng viên"})
        want = f"3. Tìm ứng viên: có {i}, cần 3" if i < 3 else "4. Đối chiếu datasheet: còn 6 ô"
        assert f.node_next(leaf) == want
    # one-node-at-a-time: binh owns only this leaf, so no warning
    assert not any("một nút" in w.lower() for w in f.tree_warnings(leaf))

    # datasheet checks with a quote and a page
    def check(uv: str, ts: str, value: float) -> None:
        f.save("doi_chieu", {"khoa": f"{uv}|{ts}", "ma_uv": uv, "ma_ts": ts, "gia_tri_so": value,
                             "trich_dan": "datasheet p.3 table 2", "trang": "3"})

    remaining = 6
    for uv, bite, depth in (("UV-001", 2100, 35), ("UV-002", 1800, 28), ("UV-003", 1600, 12)):
        check(uv, "TS-001", bite)
        remaining -= 1
        assert f.node_next(leaf) == f"4. Đối chiếu datasheet: còn {remaining} ô"
        check(uv, "TS-002", depth)
        remaining -= 1
    cmp = f.env.get("/api/node", code=leaf)["compare"]
    assert cmp["pass"] == {"UV-001": True, "UV-002": True, "UV-003": False}  # UV-003 fails the must-have depth
    assert f.env.get("/api/node", code=leaf)["candidates"][2]["_result"] == "Trượt bắt buộc"
    assert f.node_next(leaf) == "Chờ Mua hàng"
    assert f.counters()["passing_not_picked_up"] == 2
    assert [q["uv"] for q in f.env.get("/api/sourcing")["queue"]] == ["UV-001", "UV-002"]
    assert f.tree_leaf("designer", leaf)["index"] == 6 and f.tree_leaf("designer", leaf)["screen"] == "mua_hang"

    # sourcing answers: quote + lead time
    f.env.set_identity("mai", "sourcing")
    f.add("moc", "G4a", {"ten": "Prototype build", "ngay_co_so": "2027-03-31", "ngay_du_bao": "2027-03-31",
                         "trang_thai": "Kế hoạch"})
    f.save("mua_hang", {"ma_uv": "UV-001", "nha_cung_cap": "Reef Dental", "don_gia_bao": 950.0, "tien_te": "USD",
                        "tinh_trang_nguon": "Có hàng sẵn", "tg_cho_tuan": 6, "so_bao_gia": "Q-77",
                        "bao_gia_het_han": "2026-12-31", "trang_thai_mua": "Đã báo giá"})
    assert f.node_next(leaf) == "5. Chọn một ứng viên, ghi lý do"
    assert f.counters()["passing_not_picked_up"] == 1
    assert f.env.get("/api/rows", table="mua_hang")["rows"][0]["extras"]["order_by"] == "2027-02-17"  # G4a minus 6 weeks

    # the designer chooses a candidate for the leaf, gives a reason and tags the option
    f.env.set_identity("binh", "designer")
    assert f.tree_leaf("designer", leaf)["index"] == 6 and f.tree_leaf("designer", leaf)["do"].startswith("Chọn một ứng viên")
    f.update("ung_vien", "UV-001", {"trang_thai": CHOSEN, "ly_do": "Passes both must-haves, in stock", "phuong_an": "PA-B"})
    assert f.node_next(leaf) == "Xong"
    assert f.env.get("/api/tree_nodes")["nodes"][1]["next"].endswith("nút lá đã xong")
    c = f.counters()
    assert c["chosen_no_quote"] == 0 and c["chosen_no_lead_time"] == 0
    # the failing and the backup candidates: reject UV-003 with a reason, ask sourcing for UV-002 (backup)
    f.update("ung_vien", "UV-003", {"trang_thai": REJECTED, "ly_do": "Depth 12 mm is under the 20 mm minimum"})
    f.update("ung_vien", "UV-002", {"trang_thai": "Dự phòng"})
    f.env.set_identity("mai", "sourcing")
    f.save("mua_hang", {"ma_uv": "UV-002", "nha_cung_cap": "Reef Dental", "don_gia_bao": 780.0, "tien_te": "USD",
                        "tinh_trang_nguon": "Hàng về chậm", "tg_cho_tuan": 10, "trang_thai_mua": "Đã báo giá"})
    assert f.node_next(leaf) == "Xong"
    # price used by the cost roll-up is the quote: 950 USD x 25000 VND = 23.75 million VND
    cost = {n["code"]: n["cost"] for n in f.env.get("/api/tree_nodes")["nodes"]}
    assert cost[leaf] == 23.75 and cost["N3"] == 23.75 and cost["N0"] == 23.75
    assert f.counters()["passing_not_picked_up"] == 0
    assert f.counters()["rows_with_warning"] == 0  # a finished leaf leaves no warning behind

    # step 6: commit everything in dependency order
    f.env.set_identity("an", "system_designer")
    drafts = f.env.get("/api/drafts")["drafts"]
    assert drafts and all(d["valid"] for d in drafts)
    data = f.commit()
    tables = [r["table"] for r in data["results"]]
    assert tables.index("nut") < tables.index("thong_so") < tables.index("ung_vien") < tables.index("doi_chieu")
    assert tables.index("ung_vien") < tables.index("mua_hang")
    fake = f.env.fake
    assert len(fake.records("nut")) == 9 and len(fake.records("ung_vien")) == 3 and len(fake.records("doi_chieu")) == 6
    assert len(fake.records("mua_hang")) == 2 and len(fake.records("phan_bo")) == 2 and len(fake.records("thong_so")) == 2
    gates = {r["fields"]["khoa"]: r["fields"]["gia_tri"] for r in fake.records("cai_dat")
             if r["fields"]["khoa"].startswith("chot_cap")}
    assert gates == {"chot_cap_1": "Có", "chot_cap_2": "Có"}
    uv = {r["fields"]["ma_uv"]: r["fields"] for r in fake.records("ung_vien")}
    assert uv["UV-001"]["trang_thai"] == CHOSEN and uv["UV-001"]["phuong_an"] == "PA-B"
    assert uv["UV-003"]["trang_thai"] == REJECTED and uv["UV-002"]["trang_thai"] == "Dự phòng"
    assert [r["fields"]["ma_kt"] for r in fake.records("kien_truc") if r["fields"]["trang_thai"] == CHOSEN] == ["KT-B"]
    for table, id_field in (("nut", "ma_nut"), ("ung_vien", "ma_uv"), ("thong_so", "ma_ts")):  # unique
        ids = [r["fields"][id_field] for r in fake.records(table)]
        assert len(ids) == len(set(ids))
    # after the commit the app shows the same answers from Teable's data
    assert f.node_next(leaf) == "Xong" and f.env.get("/api/state")["drafts"] == 0
    final = f.counters()
    assert {k: final[k] for k in final if k != "rows_with_warning"} == {
        "must_not_allocated": 0, "pairs_missing_spec": 0, "budget_rows_over": 0, "passing_not_picked_up": 0,
        "chosen_no_quote": 0, "chosen_no_lead_time": 0}
    assert f.env.get("/api/trees")["trees"]["engineer"]["leaf"]["index"] != 0  # no drafts left


def committed_leaf_state(f: Flow) -> None:
    """Small committed project: requirements, architectures, the KT-B tree, nodes N3.1 with 1 candidate."""
    step1_requirements(f)
    step2_architectures(f)
    assert f.choose("KT-B", "Best weighted score")[0] == 200
    build_kt_b_tree(f)
    f.add("phan_bo", "PB-001", {"ma_yc": "R2", "ma_nut": "N3.1", "kieu": EACH})
    f.add("thong_so", "TS-001", {"ma_nut": "N3.1", "ma_yc_goc": "R2", "thong_so": "Bite force", "kieu": "Số",
                                 "gia_tri_min": 1500, "don_vi": "N", "muc": MUST})
    f.add("ung_vien", "UV-001", {"ma_nut": "N3.1", "hang": "Reef Dental", "model": "Great white set",
                                 "link_datasheet": "http://ds.invalid/1", "ngay_kiem_tra": "2026-10-05",
                                 "trang_thai": "Ứng viên"})
    f.commit()


def test_step6_second_user_drafts_the_same_id_conflict_new_id_accept_references_rewritten(
    flow: Flow, tmp_path: Path, fake_teable: FakeTeable
) -> None:
    f = flow
    committed_leaf_state(f)  # alice (user "an") now owns UV-001
    original = fake_teable.records("ung_vien")[0]

    def factory(url: str, token: str, **kw: Any) -> TeableClient:
        kw.update(backoff=0.0, retries=0, timeout=5.0)
        return TeableClient(url, token, **kw)

    bob = server.App(tmp_path / "bob", client_factory=factory, today=lambda: TODAY, keyring_module=None)
    try:
        bob.store.set_setting("teable_url", fake_teable.url)
        bob.store.set_setting("table_ids", f.env.table_ids)
        bob.dispatch("POST", "/api/settings", {}, {"token": "bob", "user": "binh", "role": "designer"})
        env_b = Env(bob, fake_teable, f.env.table_ids)
        # Bob's app has not refreshed since Alice committed: its cache is empty, so the nodes he refers to
        # are not known yet. He refreshes (the app does this at start) and drafts UV-001 by typing the ID.
        assert env_b.post("/api/refresh")[0] == 200
        assert env_b.get("/api/next_id", table="ung_vien")["id"] == "UV-002"  # a fresh cache proposes a free ID
        assert env_b.draft("ung_vien", {"ma_uv": "UV-001", "ma_nut": "N3.1", "hang": "Other", "model": "Tiger set",
                                        "trang_thai": "Ứng viên"})[0] == 200  # nothing warns that it exists
        assert env_b.draft("doi_chieu", {"khoa": "UV-001|TS-001", "ma_uv": "UV-001", "ma_ts": "TS-001",
                                         "gia_tri_so": 1700, "trich_dan": "p.2", "trang": "2"})[0] == 200
        status, data = env_b.post("/api/commit")
        assert status == 200 and not data["ok"]
        by_table = {r["table"]: r for r in data["results"]}
        conflict = by_table["ung_vien"]
        assert conflict["status"] == "conflict" and conflict["conflict"]["id"] == "UV-001"
        assert conflict["conflict"]["taken_by"] == "alice" or conflict["conflict"]["taken_by"]
        assert conflict["conflict"]["proposed_id"] == "UV-002" and "UV-002" in conflict["message"]
        assert by_table["doi_chieu"]["status"] == "skipped" and "UV-001" in by_table["doi_chieu"]["message"]
        status, accepted = env_b.post("/api/commit/accept", {"draft_id": conflict["draft_id"], "new_id": "UV-002"})
        assert status == 200 and accepted["rewritten"] == 1
        pending = {d["table"]: d for d in env_b.get("/api/drafts")["drafts"]}
        assert pending["doi_chieu"]["key"] == "UV-002|TS-001" and pending["doi_chieu"]["fields"]["ma_uv"] == "UV-002"
        status, data = env_b.post("/api/commit")
        assert status == 200 and data["ok"], data
        uv = {r["fields"]["ma_uv"]: r["fields"] for r in fake_teable.records("ung_vien")}
        assert uv["UV-001"]["model"] == "Great white set" and uv["UV-002"]["model"] == "Tiger set"
        assert [r for r in fake_teable.records("ung_vien") if r["fields"]["ma_uv"] == "UV-001"] == [original]
        assert fake_teable.records("doi_chieu")[0]["fields"]["ma_uv"] == "UV-002"
    finally:
        bob.close()


def test_step7_offline_keep_drafting_then_restart_and_commit(flow: Flow, fake_teable: FakeTeable) -> None:
    f = flow
    step1_requirements(f)
    f.commit()
    assert f.env.get("/api/state", force="1")["can_commit"] is True
    fake_teable.stop()
    state = f.env.get("/api/state", force="1")
    assert state["connection"]["state"] == "offline" and state["can_commit"] is False
    assert state["cache_age_seconds"] is not None and state["drafts"] == 0
    # the app is still usable: forms, IDs, validation, rules, decision tree
    assert f.new_id("kien_truc") == "KT-A"
    step2_architectures(f)
    assert f.choose("KT-B", "Best weighted score")[0] == 200
    assert f.env.get("/api/architectures")["cards"][1]["weighted"] == 4.5
    assert f.tree_leaf()["index"] == 3
    assert f.env.get("/api/state")["drafts"] == 3
    status, data = f.env.post("/api/commit")
    assert status == 503 and data["error"]["code"] in ("commit_disabled", "offline")
    assert "reachable" in data["error"]["detail"] and "commit when it is back" in data["error"]["detail"]
    status, data = f.env.post("/api/refresh")
    assert status == 503 and data["error"]["code"] == "offline"
    assert f.env.get("/api/state")["drafts"] == 3  # nothing lost
    # an ID typed twice is still caught offline
    assert f.env.draft("kien_truc", {"ma_kt": "KT-A", "ten": "dup", "trang_thai": PROPOSED})[0] == 409

    fake_teable.start()
    state = f.env.get("/api/state", force="1")
    assert state["connection"]["state"] == "online" and state["can_commit"]
    f.commit()
    assert {r["fields"]["ma_kt"]: r["fields"]["trang_thai"] for r in fake_teable.records("kien_truc")} == {
        "KT-A": PROPOSED, "KT-B": CHOSEN, "KT-C": PROPOSED}


# ====================================================================================================
# Part 2 - specifications for every leaf, RFQs through Hermes, quotes, then the decision (KT-A)
# ====================================================================================================

LEAVES = [  # code, name, owner, kind
    ("N1.1", "Legs", "binh", "Mua OEM"), ("N1.2", "Tail", "chi", "Mua OEM"), ("N1.3", "Fins", "dung", "Mua OEM"),
    ("N1.4", "Wings", "hoa", "Mua OEM"), ("N2.1", "Eye", "khanh", "Mua OEM"), ("N3.1", "Jaw", "lan", "Tự chế tạo"),
]
# code, node, name, kind, min, max, unit, level, source requirement, expected text, verification
SPECS = [
    ("TS-001", "N1.1", "Top speed", "Số", 55, 80, "km/h", MUST, "R2", "", "200 m track sprint, radar"),
    ("TS-002", "N1.1", "Stamina: sprint duration", "Số", 20, None, "s", WISH, "R2", "", "Treadmill to exhaustion"),
    ("TS-003", "N1.1", "Footfall noise at 5 m (stealth)", "Số", None, 40, "dB", MUST, "R2", "", "Microphone at 5 m"),
    ("TS-004", "N1.2", "Turning rate at 40 km/h", "Số", 120, 360, "deg/s", MUST, "R2", "", "High-speed camera"),
    ("TS-005", "N1.3", "Swim speed", "Số", 40, 70, "km/h", MUST, "R2", "", "Flume tank"),
    ("TS-006", "N1.4", "Dive speed", "Số", 100, 300, "km/h", MUST, "R2", "", "Wind tunnel"),
    ("TS-007", "N2.1", "Night-vision range", "Số", 100, None, "m", MUST, "R2", "", "Dusk trial with targets"),
    ("TS-008", "N2.1", "Threat detection", "Định tính", None, None, "", MUST, "R1",
     "Detects any larger predator at 150 m by day", "Field trial with decoys"),
    ("TS-009", "N3.1", "Bite force", "Số", 2000, None, "N", MUST, "R2", "", "Bite rig"),
]
ALLOCATIONS = [("PB-001", "R1", "N0", SYSTEM_LEVEL), ("PB-002", "R1", "N2.1", EACH), ("PB-003", "R2", "N1.1", EACH),
               ("PB-004", "R2", "N1.2", EACH), ("PB-005", "R2", "N1.3", EACH), ("PB-006", "R2", "N1.4", EACH),
               ("PB-007", "R2", "N2.1", EACH), ("PB-008", "R2", "N3.1", EACH)]
# uv, node, hang, model, cau_hinh, options, published price (a number that must never leave the machine)
CANDIDATES = [
    ("UV-001", "N1.1", "Panthera Works", "LP-4 hind limb set", "digitigrade legs, retractable claws", "PA-A", 111111.0),
    ("UV-002", "N1.2", "Panthera Works", "LT-1 long tail", "counterbalance tail, 0.9 m", "PA-A", 222222.0),
    ("UV-003", "N1.3", "Aqua Fin Ltd", "AF-9 dorsal fin set", "paired pectoral and dorsal fins", "PA-B", 333333.0),
    ("UV-004", "N1.4", "Aero Feather Co", "AW-2 wing pair", "2.4 m span, high aspect ratio", "PA-C", 444444.0),
    ("UV-005", "N2.1", "Night Optics", "TE-5 tapetum eye", "forward eyes, tapetum lucidum", "PA-A;PA-C", 555555.0),
]
CHECK_VALUES = {("UV-001", "TS-001"): 62, ("UV-001", "TS-002"): 24, ("UV-001", "TS-003"): 35, ("UV-002", "TS-004"): 200,
                ("UV-003", "TS-005"): 55, ("UV-004", "TS-006"): 180, ("UV-005", "TS-007"): 140}
BUDGET_MILLION_VND = "7777777"
# uv -> (vendor, quoted USD, availability, lead time weeks)
QUOTES = {"UV-001": ("Panthera Works", 1800.0, "Có hàng sẵn", 6), "UV-002": ("Panthera Works", 400.0, "Có hàng sẵn", 4),
          "UV-003": ("Aqua Fin Ltd", 2600.0, "Chỉ đặt theo đơn", 40), "UV-004": ("Aero Feather Co", 3100.0, "Chỉ đặt theo đơn", 36),
          "UV-005": ("Night Optics", 900.0, "Hàng về chậm", 12)}


class Confirmer:
    def __init__(self) -> None:
        self.previews: list[pa.SendPreview] = []

    def __call__(self, preview: pa.SendPreview) -> bool:
        self.previews.append(preview)
        return True


def part2_structure(f: Flow) -> None:
    """System designer: requirements, budget, milestone, three options, the tree of all five comparison parts."""
    step1_requirements(f)
    f.update("cai_dat", "ngan_sach_tr", {"gia_tri": BUDGET_MILLION_VND})
    f.add("moc", "G4a", {"ten": "Prototype build", "ngay_co_so": "2027-03-31", "ngay_du_bao": "2027-03-31"})
    step2_architectures(f)
    f.add("nut", "N0", {"ten": "Predator", "loai": "Hệ thống", "so_luong": 1})
    for code, name in (("N1", "Locomotion"), ("N2", "Sensing"), ("N3", "Bite system")):
        f.add("nut", code, {"ma_cha": "N0", "ten": name, "loai": "Cụm", "so_luong": 1}, parent="N0")
    count: dict[str, int] = {}
    for code, name, owner, kind in LEAVES:
        parent = code.split(".")[0]
        count[parent] = count.get(parent, 0) + 1
        assert code == f"{parent}.{count[parent]}"
        option = {"Fins": "KT-B", "Wings": "KT-C"}.get(name)  # fins belong to KT-B, wings to KT-C
        f.add("nut", code, {"ma_cha": parent, "ten": name, "loai": kind, "so_luong": 2 if name == "Legs" else 1,
                            "phu_trach": owner, **({"ma_kt": option} if option else {})}, parent=parent)
    f.set_gate("chot_cap_1", True)
    f.set_gate("chot_cap_2", True)
    for code, yc, node, kind in ALLOCATIONS:
        extra = {"cach_kiem_he_thong": "12-month field survey: zero predation events"} if kind == SYSTEM_LEVEL else {}
        f.add("phan_bo", code, {"ma_yc": yc, "ma_nut": node, "kieu": kind, **extra})


def part2_specs(f: Flow) -> None:
    for code, node, name, kind, low, high, unit, level, source, expected, how in SPECS:
        fields: dict[str, Any] = {"ma_nut": node, "ma_yc_goc": source, "thong_so": name, "kieu": kind, "muc": level,
                                  "kiem_chung": how}
        for key, value in (("gia_tri_min", low), ("gia_tri_max", high), ("don_vi", unit), ("mong_doi", expected)):
            if value not in (None, ""):
                fields[key] = value
        f.add("thong_so", code, fields)


def part2_candidates_and_checks(f: Flow) -> None:
    for uv, node, hang, model, config, options, price in CANDIDATES:
        f.add("ung_vien", uv, {"ma_nut": node, "hang": hang, "model": model, "cau_hinh": config, "gia_cong_bo": price,
                               "tien_te": "USD", "loai_gia": "Giá công bố", "link_datasheet": f"http://ds.invalid/{uv}",
                               "ngay_kiem_tra": "2026-10-05", "nguoi_tim": "Người", "phuong_an": options,
                               "trang_thai": "Ứng viên"})
    for (uv, ts), value in CHECK_VALUES.items():
        f.save("doi_chieu", {"khoa": f"{uv}|{ts}", "ma_uv": uv, "ma_ts": ts, "gia_tri_so": value,
                             "trich_dan": f"{uv} datasheet table 1", "trang": "2"})
    # TS-008 is qualitative: UV-005 is deliberately left unchecked for it (so it is not yet Đạt)


@pytest.fixture
def hermes() -> Any:
    with FakeHermes(polls_until_done=2) as server_:
        yield server_


def make_host(f: Flow, hermes_: FakeHermes, tmp_path: Path, user: str = "mai") -> tuple[pa.PluginHost, Confirmer]:
    confirm = Confirmer()
    host = pa.PluginHost(f.env.app.store, f.env.app.schema, user=user, plugin_dirs=[REPO / "plugins"],
                         data_dir=tmp_path / "plugdata", confirm=confirm, today=lambda: TODAY, keyring_module=None)
    for pid in ("hermes_skill", "task_outbox"):
        host.set_enabled(pid, True)
    host.discover()
    host.set_config("hermes_skill", "base_url", hermes_.url)
    host.set_secret("hermes_skill", "token", TOKEN)
    host.start()
    assert host.plugins["hermes_skill"].state == "enabled", host.plugins["hermes_skill"].error
    assert host.plugins["task_outbox"].state == "enabled", host.plugins["task_outbox"].error
    return host, confirm


def raise_rfqs(f: Flow, host: pa.PluginHost, confirm: Confirmer, hermes_: FakeHermes) -> dict[str, str]:
    """One RFQ per candidate: payload (9.2), draft in Nháp, preview, Hermes run, poll to Đã tạo, commit."""
    rfq_of: dict[str, str] = {}
    for uv, node, hang, *_ in CANDIDATES:
        try:
            start = rfq_mod.start_rfq(host.core, kind="RFQ", ma_uv=[uv], vendor=hang, reply_by="2026-10-20")
        except rfq_mod.ExtraConfirmationRequired as exc:
            assert uv == "UV-005" and exc.candidates == [("UV-005", "Chưa đủ dữ liệu")]
            assert uv not in {d.fields.get("ds_ma_uv") for d in f.env.app.store.list_drafts("rfq")}  # nothing created without it
            start = rfq_mod.start_rfq(host.core, kind="RFQ", ma_uv=[uv], vendor=hang, reply_by="2026-10-20",
                                      extra_confirm=lambda risky: True)
        rfq_of[uv] = start.ma_rfq
        payload = start.payload
        assert list(payload) == ["kind", "ma_rfq", "project", "requested_by", "language", "reply_by", "need_by",
                                 "vendor", "items", "node"]
        assert payload["need_by"] == "2027-03-31" and payload["node"] is None and payload["requested_by"] == "mai"
        item = payload["items"][0]
        assert item["ma_uv"] == uv and item["ma_nut"] == node and item["hang"] == hang and item["cau_hinh"]
        assert item["specs"] and all({"ma_ts", "thong_so", "yeu_cau", "muc"} == set(s) for s in item["specs"])
        assert rfq_mod.forbidden_paths(payload) == []
        before = len(confirm.previews)
        result = host.run_action("hermes_skill", "tao_rfq", payload)
        assert result.status == "ok", result.error
        assert len(confirm.previews) == before + 1  # the user was shown the payload and the host first
        preview = confirm.previews[-1]
        assert preview.host == hermes_.host and preview.method == "POST"
        assert json.loads(preview.payload["input"].split("Payload JSON:\n", 1)[1]) == payload
        host.poll_jobs()
        host.poll_jobs()
    assert host.status_bar_jobs() == []
    assert sorted(rfq_of.values()) == [f"RFQ-00{i}" for i in range(1, 6)]
    drafts = {d.key: d.fields for d in f.env.app.store.list_drafts("rfq")}
    assert all(d["trang_thai"] == "Đã tạo" and d["link_tai_lieu"] == hermes_.link and d["loai"] == "RFQ"
               for d in drafts.values())
    f.commit()
    return rfq_of


def assert_nothing_sensitive_left(hermes_: FakeHermes) -> None:
    body = json.dumps(hermes_.requests, ensure_ascii=False)
    for uv, *_rest, price in CANDIDATES:
        assert str(int(price)) not in body, f"published price of {uv} reached Hermes"
    assert BUDGET_MILLION_VND not in body and TOKEN not in body
    for run in hermes_.runs.values():
        assert rfq_mod.forbidden_paths(run["payload"]) == []
        text = json.dumps(run["payload"], ensure_ascii=False)
        assert "diem_" not in text and "gia_" not in text and "ngan_sach" not in text
        assert "Quote" not in text and "weighted" not in text
        # no other vendor's name or candidate leaks into a payload that is for one vendor
        others = [c for c in CANDIDATES if c[0] != run["payload"]["items"][0]["ma_uv"]]
        assert not any(c[3] in text for c in others)


def test_part2_specs_rfqs_quotes_then_choose_kt_a_and_reject_the_others(
    flow: Flow, hermes: FakeHermes, tmp_path: Path
) -> None:
    f = flow
    part2_structure(f)

    # (1) specifications: every allocated requirement has a spec on every leaf it is allocated to
    assert f.counters()["must_not_allocated"] == 0
    assert all(f.node_next(c) == "Chờ chọn kiến trúc" for c, *_ in LEAVES)  # no architecture is chosen yet
    part2_specs(f)
    assert f.counters()["pairs_missing_spec"] == 0
    a = f.env.app.analysis()
    for pair_leaf in {n for _, _, n, k in ALLOCATIONS if k != SYSTEM_LEVEL}:
        covered = {s["ma_yc_goc"] for s in f.env.get("/api/node", code=pair_leaf)["specs"]}
        allocated = {p["ma_yc"] for p in f.env.get("/api/node", code=pair_leaf)["allocations"]}
        assert allocated <= covered, (pair_leaf, allocated, covered)
    node = f.env.get("/api/node", code="N2.1")
    qualitative = next(s for s in node["specs"] if s["ma_ts"] == "TS-008")
    assert qualitative["kieu"] == "Định tính" and qualitative["mong_doi"].startswith("Detects") and not qualitative["_warnings"]
    assert all(not s["_warnings"] for n in LEAVES for s in f.env.get("/api/node", code=n[0])["specs"])
    assert a.counters()["rows_with_warning"] == 0
    part2_candidates_and_checks(f)
    assert f.env.get("/api/node", code="N2.1")["candidates"][0]["_result"] == "Chưa đủ dữ liệu"
    f.commit()  # structure, specs, candidates, checks: dependency order

    # (2) RFQs through the fake Hermes plugin
    host, confirm = make_host(f, hermes, tmp_path)
    rfq_of = raise_rfqs(f, host, confirm, hermes)
    stored = {r["fields"]["ma_rfq"]: r["fields"] for r in f.env.fake.records("rfq")}
    assert set(stored) == set(rfq_of.values()) and all(v["trang_thai"] == "Đã tạo" and v["link_tai_lieu"] == hermes.link
                                                       and v["plugin"] == "hermes_skill" and v["ma_tac_vu_ngoai"]
                                                       for v in stored.values())
    assert stored[rfq_of["UV-003"]]["ds_ma_uv"] == "UV-003" and stored[rfq_of["UV-003"]]["ds_ma_nut"] == "N1.3"
    assert len(hermes.runs) == 5 and len(confirm.previews) == 5
    assert_nothing_sensitive_left(hermes)
    sends = [e for e in host.audit_entries() if e["action"] == "tao_rfq"]
    assert len(sends) == 5 and {e["plugin"] for e in host.audit_entries()} == {"hermes_skill"}
    rows = f.env.get("/api/rows", table="rfq")["rows"]
    assert [r["fields"]["trang_thai"] for r in rows] == ["Đã tạo"] * 5

    # sending to the vendor is manual: mark Đã gửi
    for code in rfq_of.values():
        f.update("rfq", code, {"trang_thai": "Đã gửi"})
    f.commit()

    # the missing check for UV-005 comes in, then vendors reply: quoted price + lead time in mua_hang
    f.env.set_identity("khanh", "designer")
    f.save("doi_chieu", {"khoa": "UV-005|TS-008", "ma_uv": "UV-005", "ma_ts": "TS-008", "danh_gia_tay": "Đạt",
                         "trich_dan": "TE-5 sheet: detection 200 m", "trang": "4"})
    assert f.counters()["passing_not_picked_up"] == 5
    assert sorted(q["uv"] for q in f.env.get("/api/sourcing")["queue"]) == ["UV-001", "UV-002", "UV-003", "UV-004", "UV-005"]
    f.env.set_identity("mai", "sourcing")
    for uv, (vendor, usd, availability, weeks) in QUOTES.items():
        f.save("mua_hang", {"ma_uv": uv, "nha_cung_cap": vendor, "don_gia_bao": usd, "tien_te": "USD",
                            "tinh_trang_nguon": availability, "tg_cho_tuan": weeks, "so_bao_gia": f"Q-{uv}",
                            "bao_gia_het_han": "2026-12-31", "trang_thai_mua": "Đã báo giá"})
        f.update("rfq", rfq_of[uv], {"trang_thai": "Đã có trả lời"})
    assert f.counters()["passing_not_picked_up"] == 0
    f.commit()
    order_by = {r["key"]: r["extras"]["order_by"] for r in f.env.get("/api/rows", table="mua_hang")["rows"]}
    assert order_by["UV-003"] == "2026-06-24" and order_by["UV-001"] == "2027-02-17"  # G4a minus lead time
    warns = {r["key"]: r["warnings"] for r in f.env.get("/api/rows", table="mua_hang")["rows"]}
    # the 40- and 36-week quotes (fins, wings) cannot meet G4a any more: the rule says so, which backs the decision
    assert "Đã quá hạn đặt hàng" in warns["UV-003"] and "Đã quá hạn đặt hàng" in warns["UV-004"]
    assert warns["UV-001"] == [] and warns["UV-002"] == []

    # (3) decide. The quotes change the supply and time scores, then KT-A is chosen
    f.env.set_identity("an", "system_designer")
    assert {c["key"]: c["weighted"] for c in f.env.get("/api/architectures")["cards"]} == {"KT-A": 3.7, "KT-B": 4.5, "KT-C": 3.0}
    f.update("kien_truc", "KT-A", {"diem_nguon_hang": 5, "diem_thoi_gian": 5})  # legs, tail, eye: 4-12 weeks
    f.update("kien_truc", "KT-B", {"diem_nguon_hang": 1, "diem_thoi_gian": 1})  # fins: 40 weeks, order only
    f.update("kien_truc", "KT-C", {"diem_nguon_hang": 1, "diem_thoi_gian": 1})  # wings: 36 weeks, order only
    totals = {c["key"]: c["weighted"] for c in f.env.get("/api/architectures")["cards"]}
    assert totals == {"KT-A": 4.5, "KT-B": 3.0, "KT-C": 2.5}
    reason_a = ("Weighted score 4.5 against 3.0 (KT-B) and 2.5 (KT-C). Quotes: legs 6 weeks, tail 4 weeks, "
                "eye 12 weeks, all before G4a; fins 40 weeks and wings 36 weeks are order-only.")
    assert f.choose("KT-A", reason_a)[0] == 200
    f.update("kien_truc", "KT-B", {"trang_thai": REJECTED, "ly_do": "Weighted 3.0: fin quote needs 40 weeks (RFQ answered)"})
    f.update("kien_truc", "KT-C", {"trang_thai": REJECTED, "ly_do": "Weighted 2.5: wing quote needs 36 weeks, mass limit"})
    assert all(not c["warnings"] for c in f.env.get("/api/architectures")["cards"])
    assert f.tree_leaf()["index"] != 2  # exactly one chosen, with a reason
    f.commit()
    status_of = {r["fields"]["ma_kt"]: r["fields"]["trang_thai"] for r in f.env.fake.records("kien_truc")}
    assert status_of == {"KT-A": CHOSEN, "KT-B": REJECTED, "KT-C": REJECTED}
    reasons = {r["fields"]["ma_kt"]: r["fields"]["ly_do"] for r in f.env.fake.records("kien_truc")}
    assert "4.5" in reasons["KT-A"] and "40 weeks" in reasons["KT-B"] and "36 weeks" in reasons["KT-C"]
    # the leaves now show real next actions instead of "Chờ chọn kiến trúc"
    assert f.node_next("N1.1") == "3. Tìm ứng viên: có 1, cần 3" and f.node_next("N3.1") == "3. Tìm ứng viên: có 0, cần 1"
    assert f.counters()["chosen_no_quote"] == 0  # nothing is chosen yet at leaf level
    # the candidates remain in the data, tagged with their options
    uv = {r["fields"]["ma_uv"]: r["fields"] for r in f.env.fake.records("ung_vien")}
    assert uv["UV-003"]["phuong_an"] == "PA-B" and uv["UV-004"]["phuong_an"] == "PA-C" and uv["UV-005"]["phuong_an"] == "PA-A;PA-C"
    assert f.env.get("/api/trees")["trees"]["system_design"]["leaf"]["index"] >= 5


def tasks_after_decision(f: Flow, hermes_: FakeHermes, tmp_path: Path) -> set[str]:
    """Run the whole follow-up, rebuild the task list with the task_outbox plugin, return the open task keys."""
    part2_structure(f)
    part2_specs(f)
    part2_candidates_and_checks(f)
    f.save("doi_chieu", {"khoa": "UV-005|TS-008", "ma_uv": "UV-005", "ma_ts": "TS-008", "danh_gia_tay": "Đạt",
                         "trich_dan": "TE-5 sheet: detection 200 m", "trang": "4"})
    f.commit()
    host, confirm = make_host(f, hermes_, tmp_path)
    raise_rfqs(f, host, confirm, hermes_)
    assert f.choose("KT-A", "Weighted score 4.5; legs, tail, eye quotes are on time")[0] == 200
    f.update("kien_truc", "KT-B", {"trang_thai": REJECTED, "ly_do": "Fin quote needs 40 weeks"})
    f.update("kien_truc", "KT-C", {"trang_thai": REJECTED, "ly_do": "Wing quote needs 36 weeks"})
    f.commit()
    assert host.run_action("task_outbox", "rebuild").status == "ok"
    keys = {d.key for d in f.env.app.store.list_drafts("cong_viec")}
    f.commit()
    open_in_teable = {r["fields"]["ma_cv"] for r in f.env.fake.records("cong_viec") if r["fields"]["trang_thai"] == "Mở"}
    assert open_in_teable == keys
    return keys


def test_part2_task_outbox_after_the_decision(flow: Flow, hermes: FakeHermes, tmp_path: Path) -> None:
    keys = tasks_after_decision(flow, hermes, tmp_path)
    # leaves of the chosen option have their step task
    assert {"CV|buoc|N1.1", "CV|buoc|N1.2", "CV|buoc|N2.1", "CV|buoc|N3.1"} <= keys
    # comparison RFQs are answered (not Đã gửi and overdue), so they never become tasks
    assert not any(k.startswith("CV|rfq|") for k in keys)


def test_part2_rejected_option_leaves_must_not_have_open_tasks(flow: Flow, hermes: FakeHermes, tmp_path: Path) -> None:
    keys = tasks_after_decision(flow, hermes, tmp_path)
    assert "CV|buoc|N1.3" not in keys and "CV|buoc|N1.4" not in keys  # fins (KT-B) and wings (KT-C)


def test_part2_rfq_payload_for_a_node_has_no_price_budget_or_score(flow: Flow, hermes: FakeHermes, tmp_path: Path) -> None:
    """An RFP for the eye (needs the node's allocated requirements and specs) is as clean as an RFQ."""
    f = flow
    part2_structure(f)
    part2_specs(f)
    f.commit()
    host, confirm = make_host(f, hermes, tmp_path)
    start = rfq_mod.start_rfq(host.core, kind="RFP", ma_nut="N2.1")
    assert start.ma_rfq == "RFP-001" and start.payload["items"] == []
    node = start.payload["node"]
    assert node["ma_nut"] == "N2.1" and [r["ma_yc"] for r in node["yeu_cau"]] == ["R1", "R2"]
    assert [s["yeu_cau"] for s in node["specs"]] == ["≥ 100 m", "Detects any larger predator at 150 m by day"]
    assert node["yeu_cau"][0]["tieu_chi_nghiem_thu"].startswith("No natural predator")
    assert rfq_mod.forbidden_paths(start.payload) == []
    assert host.run_action("hermes_skill", "tao_rfp", start.payload).status == "ok"
    host.poll_jobs()
    host.poll_jobs()
    f.commit()
    assert f.env.fake.records("rfq")[0]["fields"]["trang_thai"] == "Đã tạo"
    assert BUDGET_MILLION_VND not in json.dumps(hermes.requests)


def test_names_travel_with_every_screen_so_codes_are_never_shown_alone(flow: Flow) -> None:
    """The UI shows "N1 - Propulsion" in pickers, tables, matrix headers: every screen payload carries the names."""
    f = flow
    step1_requirements(f)
    step2_architectures(f)
    build_kt_b_tree(f)
    f.add("phan_bo", "PB-001", {"ma_yc": "R2", "ma_nut": "N3.1", "kieu": EACH})
    expected = {"nut": "Propulsion (fin/tail)", "yeu_cau": "Hunt well", "kien_truc": "Aquatic hunter"}
    for path, query in (("/api/rows", {"table": "phan_bo"}), ("/api/alloc", {}), ("/api/tree_nodes", {}),
                        ("/api/sourcing", {}), ("/api/node", {"code": "N3.1"})):
        names = f.env.get(path, **query)["names"]
        assert names["nut"]["N1"] == expected["nut"] and names["nut"]["N3.1"] == "Sharp teeth"
        assert names["yeu_cau"]["R2"] == expected["yeu_cau"] and names["kien_truc"]["KT-B"] == expected["kien_truc"]
    # drafts count too: a node that is only a draft is named
    assert f.env.get("/api/rows", table="nut")["names"]["nut"]["N0"] == "Predator"
