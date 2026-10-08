"""UI server: API against fake_teable, acceptance tests 2/5/8 through the API, 10 and 15."""

from __future__ import annotations

import json
import re
import shutil
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from fake_teable import FakeTeable
from fixtures.pressure_tank import TODAY, build
from t3desk import schema as schema_mod
from t3desk import server
from t3desk.teable_client import TeableClient

UI_DIR = server.UI_DIR


class Env:
    """An App wired to the fake Teable, with helpers to call the API and load fixture data."""

    def __init__(self, app: server.App, fake: FakeTeable, table_ids: dict[str, str]):
        self.app, self.fake, self.table_ids = app, fake, table_ids

    def call(self, method: str, path: str, query: dict[str, str] | None = None, body: Any = None) -> tuple[int, Any]:
        return self.app.dispatch(method, path, query or {}, body)

    def get(self, path: str, **query: str) -> Any:
        status, data = self.call("GET", path, query)
        assert status == 200, data
        return data

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        return self.call("POST", path, None, body if body is not None else {})

    def draft(self, table: str, fields: dict[str, Any], **extra: Any) -> tuple[int, Any]:
        return self.post("/api/draft", {"table": table, "fields": fields, **extra})

    def load_cache(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        for name, rows in tables.items():
            records = [{"id": f"rec{name}{i}", "fields": r, "lastModifiedTime": "2026-10-01T00:00:00.000Z",
                        "createdTime": "2026-10-01T00:00:00.000Z"} for i, r in enumerate(rows)]
            self.app.store.replace_cache(name, records)
        self.app._bump()

    def set_identity(self, user: str = "an", role: str = "system_designer") -> None:
        status, data = self.post("/api/settings", {"user": user, "role": role})
        assert status == 200, data


@pytest.fixture
def env(tmp_path: Path, fake_teable: FakeTeable, bootstrapped: dict[str, Any]) -> Iterator[Env]:
    def factory(url: str, token: str, **kw: Any) -> TeableClient:
        kw.setdefault("backoff", 0.0)
        kw.setdefault("retries", 0)
        kw.setdefault("timeout", 5.0)
        return TeableClient(url, token, **kw)

    app = server.App(tmp_path / "home", client_factory=factory, today=lambda: TODAY, keyring_module=None)
    app.store.set_setting("teable_url", fake_teable.url)
    app.store.set_setting("table_ids", bootstrapped["table_ids"])
    status, data = app.dispatch("POST", "/api/settings", {}, {"token": "alice", "user": "an", "role": "system_designer"})
    assert status == 200, data
    yield Env(app, fake_teable, bootstrapped["table_ids"])
    app.close()


@pytest.fixture
def loaded(env: Env) -> Env:
    env.load_cache(build())
    return env


# ---- HTTP layer ---------------------------------------------------------------


@pytest.fixture
def http(env: Env) -> Iterator[tuple[server.RunningServer, Env]]:
    running = server.make_server(env.app).start()
    yield running, env
    running.stop()


def fetch(running: server.RunningServer, path: str, *, headers: dict[str, str] | None = None,
          data: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(running.url.rstrip("/") + path, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_serves_ui_files_and_injects_the_session(http: tuple[server.RunningServer, Env]) -> None:
    running, env = http
    status, body = fetch(running, "/")
    assert status == 200 and b"T3 Desk" in body
    assert env.app.session.encode() in body and b"__SESSION__" not in body
    for name in ("app.js", "tree.js", "style.css"):
        assert fetch(running, "/" + name)[0] == 200
    assert fetch(running, "/server.py")[0] == 404
    assert fetch(running, "/../server.py")[0] in (403, 404)


def test_api_needs_the_session_header_and_a_loopback_host(http: tuple[server.RunningServer, Env]) -> None:
    running, env = http
    assert fetch(running, "/api/meta")[0] == 403
    assert fetch(running, "/api/meta", headers={server.SESSION_HEADER: "wrong"})[0] == 403
    status, body = fetch(running, "/api/meta", headers={server.SESSION_HEADER: env.app.session})
    assert status == 200 and "schema" in json.loads(body)
    status, _ = fetch(running, "/api/meta", headers={server.SESSION_HEADER: env.app.session, "Host": "evil.example"})
    assert status == 403
    # a POST that is not JSON is refused (a cross-site form cannot send JSON)
    status, _ = fetch(running, "/api/draft", headers={server.SESSION_HEADER: env.app.session,
                                                       "Content-Type": "text/plain"}, data=b"{}")
    assert status == 415


def test_server_listens_on_loopback_only(http: tuple[server.RunningServer, Env]) -> None:
    running, _ = http
    assert running.httpd.server_address[0] == "127.0.0.1" and running.port > 0


# ---- labels, static content ---------------------------------------------------


def ui_labels() -> dict[str, str]:
    return server.load_ui_labels()["ui"]


def test_every_label_the_ui_asks_for_exists() -> None:
    labels = ui_labels()
    js = (UI_DIR / "app.js").read_text(encoding="utf-8") + (UI_DIR / "index.html").read_text(encoding="utf-8")
    literal = set(re.findall(r"T\('([a-z_0-9]+)'", js)) | set(re.findall(r'data-i(?:-title)?="([a-z_0-9]+)"', js))
    literal = {k for k in literal if not k.endswith("_")}
    expected = set(literal)
    expected |= {"nav_" + s for s in server.SCREENS} | {"role_" + r for r in server.ROLES}
    expected |= {"tree_" + t for t in ("system_design", "designer", "engineer")}
    expected |= {"conn_" + c for c in ("online", "offline", "unconfigured", "auth", "error")}
    expected |= {"res_" + r for r in ("committed", "conflict", "failed", "stale", "skipped")}
    expected |= {"state_" + r for r in ("pass", "fail", "unchecked")} | {"op_create", "op_update"}
    expected |= {"gate_" + g for g in server.GATE_KEYS}
    expected |= {"set_" + k for k in re.findall(r"row\('([a-z_]+)'", js)}
    expected |= {"v_" + c for c in ("id_format", "required", "not_allowed", "type", "range", "unknown_field", "rate_invalid", "rate_old_unit",
                                   "missing_ref", "id_immutable", "self_ref")}
    expected |= {"extra_" + c for c in ("n_nodes", "level", "cost", "next_action", "result", "price_mvnd", "order_by")}
    src = Path(server.__file__).read_text(encoding="utf-8")
    expected |= {"err_" + c for c in re.findall(r'ApiError\(\s*\d+,\s*"([a-z_]+)"', src)}
    expected |= {"err_" + c for c in ("net", "internal", "invalid", "screen", "bad_host", "bad_session", "no_route")}
    missing = sorted(k for k in expected if k not in labels)
    assert not missing, f"labels_ui_vi.yaml lacks: {missing}"


def test_ui_files_have_no_vietnamese_literals_and_no_external_urls() -> None:
    vietnamese = re.compile("[À-ÃÈ-ÊÌÍÒ-ÕÙÚÝà-ãè-ê"
                            "ìíò-õùúýĂăĐđĨĩŨũ"
                            "ƠơƯưẠ-ỹ]")
    for name in ("index.html", "app.js", "tree.js", "style.css"):
        text = (UI_DIR / name).read_text(encoding="utf-8")
        assert not vietnamese.search(text), f"{name} holds Vietnamese text; move it to labels_ui_vi.yaml"
        urls = [u for u in re.findall(r"https?://[A-Za-z0-9][^\s'\"]*", text) if u != "http://www.w3.org/2000/svg"]
        assert not urls, f"{name} mentions an external URL: {urls}"  # the SVG namespace id is not a fetch
        assert "@import" not in text and "fonts.googleapis" not in text
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'(src|href)="(?!/)', html), "index.html must load only local files"


def test_meta_carries_schema_labels_and_screens(env: Env) -> None:
    meta = env.get("/api/meta")
    assert set(meta["screens"]) == set(server.SCREENS) and len(meta["screens"]) == 11
    assert "yeu_cau" in meta["schema"]["tables"] and meta["labels"]["ui"]["nav_commit"]
    assert meta["role_tree"]["designer"] == "designer"


# ---- state, settings ----------------------------------------------------------


def test_state_never_returns_the_token(env: Env) -> None:
    state = env.get("/api/state", force="1")
    assert state["has_token"] is True and "alice" not in json.dumps(state)
    assert state["connection"]["state"] == "online" and state["can_commit"] is True
    assert not any("alice" in str(v) for v in env.app.store.all_settings().values())


def test_role_picks_default_screen_and_tree(env: Env) -> None:
    env.set_identity("binh", "designer")
    state = env.get("/api/state")
    assert state["default_screen"] == "nut" and state["tree"] == "designer"
    assert env.get("/api/trees")["first"] == "designer"


def test_bad_role_is_refused(env: Env) -> None:
    status, data = env.post("/api/settings", {"role": "boss"})
    assert status == 422 and data["error"]["code"] == "bad_role"


def test_connection_test_reports_the_server_message(env: Env) -> None:
    status, data = env.post("/api/connection/test", {"teable_url": env.fake.url, "token": "alice"})
    assert status == 200 and data["ok"]


def test_bootstrap_through_the_api_opens_a_project(tmp_path: Path, fake_teable: FakeTeable) -> None:
    app = server.App(tmp_path / "h2", today=lambda: TODAY, keyring_module=None)
    try:
        app.dispatch("POST", "/api/settings", {}, {"teable_url": fake_teable.url, "token": "alice", "user": "an", "role": "pm"})
        status, data = app.dispatch("POST", "/api/bootstrap", {}, {"project_name": "Demo", "space_id": "spc1"})
        assert status == 200, data
        assert len(data["table_ids"]) == 14
        state = app.dispatch("GET", "/api/state", {}, None)[1]
        assert state["has_project"] and state["project"] == "Demo"
        assert app.dispatch("POST", "/api/bootstrap", {}, {})[1]["error"]["code"] == "need_base_or_name"
    finally:
        app.close()


# ---- tables, filters, csv -----------------------------------------------------


def test_rows_filter_by_node_and_owner(loaded: Env) -> None:
    all_nodes = loaded.get("/api/rows", table="nut")
    assert [r["key"] for r in all_nodes["rows"]][:3] == ["N0", "N1", "N1.1"]
    mine = loaded.get("/api/rows", table="nut", owner="an")
    assert [r["key"] for r in mine["rows"]] == ["N1.1"]
    cands = loaded.get("/api/rows", table="ung_vien", node="N1.2")
    assert [r["key"] for r in cands["rows"]] == ["UV-004", "UV-005"]
    checks = loaded.get("/api/rows", table="doi_chieu", node="N1.2")
    assert len(checks["rows"]) == 2  # filtered through the candidate's node
    assert loaded.call("GET", "/api/rows", {"table": "nope"})[0] == 404


def test_extra_columns_are_computed_not_stored(loaded: Env) -> None:
    yc = {r["key"]: r for r in loaded.get("/api/rows", table="yeu_cau")["rows"]}
    assert yc["R2"]["extras"]["n_nodes"] == 2
    nodes = {r["key"]: r for r in loaded.get("/api/rows", table="nut")["rows"]}
    assert nodes["N1.1"]["extras"]["next_action"] == "Xong"
    assert "có 2, cần 3" in nodes["N1.2"]["extras"]["next_action"]
    assert nodes["N1"]["extras"]["next_action"].endswith("nút lá đã xong")


def test_csv_export_has_bom_header_and_respects_filters(loaded: Env) -> None:
    data = loaded.get("/api/csv", table="nut", owner="an")
    text = data["text"]
    assert text.startswith("﻿") and data["filename"] == "nut.csv"
    lines = text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("ma_nut,") and len(lines) == 2 and lines[1].startswith("N1.1,")


def test_overview_lists_my_leaves_counters_and_warnings(loaded: Env) -> None:
    env = loaded
    env.set_identity("binh", "designer")
    data = env.get("/api/overview")
    assert [(x["code"]) for x in data["leaves"]] == ["N1.2"]
    assert "có 2, cần 3" in data["leaves"][0]["next"]
    counters = {c["name"]: c["value"] for c in data["counters"]}
    assert counters["pairs_missing_spec"] == 1 and len(data["counters"]) == 7
    assert any(w["key"] == "PB-004" for w in data["warnings"])


# ---- drafts -------------------------------------------------------------------


def test_save_draft_marks_the_row_and_counts(loaded: Env) -> None:
    status, data = loaded.draft("yeu_cau", {"ma_yc": "R7", "mo_ta": "Mới", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    assert status == 200 and data["drafts"] == 1
    rows = {r["key"]: r for r in loaded.get("/api/rows", table="yeu_cau")["rows"]}
    assert rows["R7"]["draft"] and rows["R7"]["draft_op"] == "create" and rows["R1"]["draft"] is None
    assert loaded.get("/api/state")["drafts"] == 1


def test_draft_validation_errors_come_back_per_field(loaded: Env) -> None:
    status, data = loaded.draft("yeu_cau", {"ma_yc": "X9", "muc": "Sai"})
    assert status == 422 and data["error"]["code"] == "invalid"
    assert {i["field"] for i in data["error"]["issues"]} >= {"ma_yc", "mo_ta", "muc"}
    status, data = loaded.draft("thong_so", {"ma_ts": "TS-009", "ma_nut": "N9.9", "ma_yc_goc": "R1",
                                            "thong_so": "x", "kieu": "Số", "muc": "Bắt buộc"})
    assert status == 422 and any(i["code"] == "missing_ref" for i in data["error"]["issues"])
    assert loaded.app.store.count_drafts() == 0


def test_duplicate_local_draft_is_refused(loaded: Env) -> None:
    fields = {"ma_yc": "R7", "mo_ta": "a", "muc": "Bắt buộc", "trang_thai": "Nháp"}
    assert loaded.draft("yeu_cau", fields)[0] == 200
    status, data = loaded.draft("yeu_cau", fields)
    assert status == 409 and data["error"]["code"] == "duplicate_draft"


def test_editing_a_draft_replaces_it_and_discard_is_local(loaded: Env) -> None:
    fields = {"ma_yc": "R7", "mo_ta": "a", "muc": "Bắt buộc", "trang_thai": "Nháp"}
    draft_id = loaded.draft("yeu_cau", fields)[1]["draft"]["id"]
    status, data = loaded.draft("yeu_cau", {**fields, "mo_ta": "b"}, draft_id=draft_id)
    assert status == 200 and data["draft"]["fields"]["mo_ta"] == "b" and data["drafts"] == 1
    assert loaded.post("/api/draft/discard", {"draft_id": draft_id})[1]["drafts"] == 0
    assert loaded.fake.records("yeu_cau") == []  # nothing ever reached Teable


def test_next_id_counts_cache_and_drafts(loaded: Env) -> None:
    assert loaded.get("/api/next_id", table="yeu_cau")["id"] == "R7"
    loaded.draft("yeu_cau", {"ma_yc": "R7", "mo_ta": "a", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    assert loaded.get("/api/next_id", table="yeu_cau")["id"] == "R8"
    assert loaded.get("/api/next_id", table="ung_vien")["id"] == "UV-006"
    assert loaded.get("/api/next_id", table="nut", parent="N1")["id"] == "N1.3"


# ---- role enforcement ---------------------------------------------------------


@pytest.mark.parametrize("role", ["designer", "engineer", "sourcing", "pm"])
def test_only_system_designer_sets_gates_and_chooses_architecture(loaded: Env, role: str) -> None:
    loaded.set_identity("x", role)
    status, data = loaded.draft("cai_dat", {"khoa": "chot_cap_1", "gia_tri": "Không"})
    assert status == 403 and data["error"]["code"] == "role_required"
    status, data = loaded.draft("kien_truc", {"ma_kt": "KT-C", "ten": "C", "trang_thai": "Chọn", "ly_do": "x"})
    assert status == 403
    status, data = loaded.post("/api/draft", {"table": "kien_truc", "op": "update", "key": "KT-B", "record_id": "recX",
                                              "fields": {"trang_thai": "Chọn"}})
    assert status == 403
    assert loaded.app.store.count_drafts() == 0
    # other cai_dat rows and other architecture states are open to everyone
    assert loaded.draft("kien_truc", {"ma_kt": "KT-C", "ten": "C", "trang_thai": "Đề xuất"})[0] == 200


def test_system_designer_may_set_gate_and_choose(loaded: Env) -> None:
    loaded.set_identity("an", "system_designer")
    rows = {r["key"]: r for r in loaded.get("/api/rows", table="cai_dat")["rows"]}
    gate = rows["chot_cap_2"]
    status, data = loaded.post("/api/draft", {"table": "cai_dat", "op": "update", "key": "chot_cap_2",
                                              "record_id": gate["record_id"], "base_modified": gate["modified"],
                                              "base_fields": gate["base"], "fields": {"gia_tri": "Không"}})
    assert status == 200, data
    nodes = loaded.get("/api/tree_nodes")
    assert nodes["gates"] == {"chot_cap_1": True, "chot_cap_2": False} and nodes["can_gate"]
    assert loaded.get("/api/architectures")["can_choose"]


def test_choose_architecture_that_is_still_a_new_draft(loaded: Env) -> None:
    """Choosing KT-C before it is committed sends only the status and reason; ma_kt must not be 'required'."""
    loaded.set_identity("an", "system_designer")
    status, data = loaded.draft("kien_truc", {"ma_kt": "KT-C", "ten": "C", "trang_thai": "Đề xuất",
                                              "diem_ky_thuat": 4, "diem_nguon_hang": 3, "diem_thoi_gian": 5})
    assert status == 200, data
    draft_id = data["draft"]["id"]
    status, data = loaded.post("/api/draft", {"table": "kien_truc", "op": "update", "key": "KT-C", "draft_id": draft_id,
                                              "fields": {"trang_thai": "Chọn", "ly_do": "Best total score"}})
    assert status == 200, data
    assert data["draft"]["op"] == "create" and data["draft"]["valid"]
    assert data["draft"]["fields"]["ma_kt"] == "KT-C" and data["draft"]["fields"]["ten"] == "C"
    assert data["draft"]["fields"]["trang_thai"] == "Chọn" and data["draft"]["fields"]["diem_ky_thuat"] == 4
    assert loaded.app.store.count_drafts() == 1


def test_role_is_rechecked_at_commit(loaded: Env) -> None:
    loaded.draft("kien_truc", {"ma_kt": "KT-C", "ten": "C", "trang_thai": "Chọn", "ly_do": "x"})
    loaded.set_identity("an", "engineer")
    status, data = loaded.post("/api/commit")
    assert status == 403 and data["error"]["code"] == "role_required"


# ---- screens data -------------------------------------------------------------


def test_architecture_cards_weighted_total(loaded: Env) -> None:
    loaded.app.store.replace_cache("cai_dat", [
        {"id": f"c{i}", "fields": {"khoa": k, "gia_tri": v}, "lastModifiedTime": "t"}
        for i, (k, v) in enumerate([("trong_so_ky_thuat", "0.5"), ("trong_so_nguon_hang", "0.3"), ("trong_so_thoi_gian", "0.2")])])
    loaded.app.store.replace_cache("kien_truc", [
        {"id": "r1", "fields": {"ma_kt": "KT-A", "ten": "A", "trang_thai": "Chọn", "ly_do": "x",
                                "diem_ky_thuat": 5, "diem_nguon_hang": 3, "diem_thoi_gian": 2}, "lastModifiedTime": "t"}])
    loaded.app._bump()
    card = loaded.get("/api/architectures")["cards"][0]
    assert card["weighted"] == round((5 * 0.5 + 3 * 0.3 + 2 * 0.2) / 1.0, 2)


def test_tree_screen_data(loaded: Env) -> None:
    data = loaded.get("/api/tree_nodes")
    codes = [n["code"] for n in data["nodes"]]
    assert codes[:4] == ["N0", "N1", "N1.1", "N1.2"]
    byc = {n["code"]: n for n in data["nodes"]}
    assert byc["N1.1"]["level"] == 2 and byc["N1.1"]["depth"] == 2 and byc["N1.1"]["next"] == "Xong"
    assert byc["N1"]["leaf"] is False and byc["N1.1"]["cost"] > 0


def test_allocation_matrix_and_budget(loaded: Env) -> None:
    data = loaded.get("/api/alloc")
    assert data["cells"]["R1|N1.1"]["key"] == "PB-001"
    assert data["budgets"]["R4"]["total"] == 90.0 and data["budgets"]["R4"]["margin"] == 10.0
    assert "N0" in data["nodes"]  # the system-level pair PB-011 stays reachable


def test_node_screen_comparison_has_quoted_values_and_results(loaded: Env) -> None:
    data = loaded.get("/api/node", code="N1.1")
    cmp = data["compare"]
    assert cmp["candidates"] == ["UV-001", "UV-002"]  # the rejected candidate is not compared
    row = next(r for r in cmp["rows"] if r["ts"] == "TS-001")
    assert row["cells"][0]["value"] == -170 and row["cells"][0]["state"] == "pass"
    assert cmp["pass"] == {"UV-001": True, "UV-002": True}
    assert len(data["specs"]) == 2 and len(data["candidates"]) == 3
    assert loaded.get("/api/node")["node"] is None  # no code: the leaf picker


def test_sourcing_queue_lists_passing_candidates_without_a_row(loaded: Env) -> None:
    queue = loaded.get("/api/sourcing")["queue"]
    assert [q["uv"] for q in queue] == ["UV-002", "UV-004", "UV-005"]  # passing, rejected excluded, no mua_hang row


# ---- commit through the API ---------------------------------------------------


def test_commit_sends_in_dependency_order_and_clears_drafts(env: Env) -> None:
    env.draft("nut", {"ma_nut": "N0", "ten": "Gốc", "loai": "Hệ thống", "so_luong": 1})
    env.draft("nut", {"ma_nut": "N1", "ma_cha": "N0", "ten": "Cụm", "loai": "Cụm", "so_luong": 1})
    status, data = env.post("/api/commit")
    assert status == 200 and data["ok"] and data["drafts"] == 0
    assert [r["status"] for r in data["results"]] == ["committed", "committed"]
    assert {r["fields"]["ma_nut"] for r in env.fake.records("nut")} == {"N0", "N1"}
    rows = env.get("/api/rows", table="nut")["rows"]  # the cache was refreshed
    assert [r["key"] for r in rows] == ["N0", "N1"] and all(r["draft"] is None for r in rows)


def test_acceptance_2_conflict_rename_and_rewrite_through_the_api(env: Env) -> None:
    env.fake.seed("nut", {"ma_nut": "N0", "ten": "Gốc", "loai": "Hệ thống"}, user="A")
    env.fake.seed("ung_vien", {"ma_uv": "UV-007", "ma_nut": "N0", "hang": "A-hãng", "model": "m", "trang_thai": "Ứng viên"}, user="A")
    env.fake.seed("thong_so", {"ma_ts": "TS-001", "ma_nut": "N0", "ma_yc_goc": "Dẫn xuất", "thong_so": "t",
                               "kieu": "Số", "muc": "Bắt buộc"}, user="A")
    assert env.post("/api/refresh")[0] == 200
    assert env.draft("ung_vien", {"ma_uv": "UV-007", "ma_nut": "N0", "hang": "B-hãng", "model": "m", "trang_thai": "Ứng viên"})[0] == 200
    assert env.draft("doi_chieu", {"khoa": "UV-007|TS-001", "ma_uv": "UV-007", "ma_ts": "TS-001",
                                   "danh_gia_tay": "Đạt", "trich_dan": "q", "trang": "3"})[0] == 200
    status, data = env.post("/api/commit")
    assert status == 200 and not data["ok"]
    by_table = {r["table"]: r for r in data["results"]}
    conflict = by_table["ung_vien"]
    assert conflict["status"] == "conflict" and conflict["conflict"]["proposed_id"] == "UV-008"
    assert conflict["conflict"]["id"] == "UV-007" and conflict["conflict"]["taken_by"]
    assert by_table["doi_chieu"]["status"] == "skipped"
    status, accepted = env.post("/api/commit/accept", {"draft_id": conflict["draft_id"], "new_id": "UV-008"})
    assert status == 200 and accepted["rewritten"] == 1
    status, data = env.post("/api/commit")
    assert status == 200 and data["ok"], data
    uv = {r["fields"]["ma_uv"]: r["fields"] for r in env.fake.records("ung_vien")}
    assert uv["UV-007"]["hang"] == "A-hãng" and uv["UV-008"]["hang"] == "B-hãng"
    assert env.fake.records("doi_chieu")[0]["fields"]["ma_uv"] == "UV-008"
    status, bad = env.post("/api/commit/accept", {"draft_id": 999, "new_id": "UV-009"})
    assert status == 422 and bad["error"]["code"] == "bad_new_id"


def test_acceptance_5_stale_edit_offers_both_versions_per_field(env: Env, make_client: Callable[..., TeableClient]) -> None:
    rec = env.fake.seed("yeu_cau", {"ma_yc": "R1", "mo_ta": "gốc", "muc": "Bắt buộc", "trang_thai": "Nháp"}, user="B")
    env.post("/api/refresh")
    row = env.get("/api/rows", table="yeu_cau")["rows"][0]
    other = make_client("bob")
    other.update_record(env.table_ids["yeu_cau"], rec["id"], {"mo_ta": "của B"})
    status, _ = env.post("/api/draft", {"table": "yeu_cau", "op": "update", "key": "R1", "record_id": row["record_id"],
                                        "base_modified": row["modified"], "base_fields": row["base"],
                                        "fields": {"mo_ta": "của A", "uu_tien": "H"}})
    assert status == 200
    status, data = env.post("/api/commit")
    stale = data["results"][0]
    assert status == 200 and stale["status"] == "stale"
    fields = {f["field"]: f for f in stale["stale"]["fields"]}
    assert fields["mo_ta"]["theirs"] == "của B" and fields["mo_ta"]["mine"] == "của A" and fields["mo_ta"]["theirs_changed"]
    status, res = env.post("/api/commit/stale", {"draft_id": stale["draft_id"], "choices": {"mo_ta": "theirs", "uu_tien": "mine"}})
    assert status == 200 and res["remaining"]
    status, data = env.post("/api/commit")
    assert data["ok"], data
    final = env.fake.records("yeu_cau")[0]["fields"]
    assert final["mo_ta"] == "của B" and final["uu_tien"] == "H"


def test_commit_refused_when_unique_flag_is_gone(env: Env) -> None:
    env.draft("yeu_cau", {"ma_yc": "R1", "mo_ta": "a", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    env.fake.drop_unique("yeu_cau", "ma_yc")
    status, data = env.post("/api/commit")
    assert status == 409 and data["error"]["code"] == "unique_flag_missing"
    assert "yeu_cau.ma_yc" in data["error"]["detail"]
    assert env.app.store.count_drafts() == 1 and env.fake.records("yeu_cau") == []


# ---- acceptance test 8: offline -----------------------------------------------


def test_acceptance_8_offline_cache_age_draft_survives_restart_commit_disabled(
    env: Env, fake_teable: FakeTeable, tmp_path: Path
) -> None:
    env.load_cache(build())
    env.app.store.replace_cache("yeu_cau", env.app.store.cache_records("yeu_cau"))  # stamp a fetch time
    fake_teable.stop()
    state = env.get("/api/state", force="1")
    assert state["connection"]["state"] == "offline" and state["can_commit"] is False
    assert state["cache_age_seconds"] is not None
    assert len(env.get("/api/rows", table="nut")["rows"]) == 10  # cached data still served
    assert env.draft("yeu_cau", {"ma_yc": "R9", "mo_ta": "offline", "muc": "Bắt buộc", "trang_thai": "Nháp"})[0] == 200
    status, data = env.post("/api/commit")
    assert status == 503 and data["error"]["code"] in ("commit_disabled", "offline")
    assert env.app.store.count_drafts() == 1
    home = env.app.home
    env.app.close()
    again = server.App(home, today=lambda: TODAY, keyring_module=None)  # "restart"
    try:
        drafts = again.dispatch("GET", "/api/drafts", {}, None)[1]["drafts"]
        assert [d["key"] for d in drafts] == ["R9"]
        assert again.dispatch("GET", "/api/rows", {"table": "nut"}, None)[1]["age"] is not None
    finally:
        again.close()
    env.app = server.App(tmp_path / "unused", today=lambda: TODAY, keyring_module=None)  # fixture teardown closes this


def test_unconfigured_app_starts_and_says_so(tmp_path: Path) -> None:
    app = server.App(tmp_path / "fresh", keyring_module=None)
    try:
        state = app.dispatch("GET", "/api/state", {}, None)[1]
        assert state["connection"]["state"] == "unconfigured" and state["default_screen"] == "khoi_tao"
        status, data = app.dispatch("POST", "/api/commit", {}, {})
        assert status == 409 and data["error"]["code"] == "no_project"
        status, data = app.dispatch("GET", "/api/trees", {}, None)
        assert status == 200 and data["trees"]["system_design"]["questions"]
    finally:
        app.close()


def test_unexpected_error_is_reported_not_swallowed(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(query: dict[str, str], body: Any) -> Any:
        raise RuntimeError("kaput")

    monkeypatch.setitem(env.app.routes, ("GET", "/api/boom"), boom)
    status, data = env.call("GET", "/api/boom")
    assert status == 500 and data["error"]["code"] == "internal" and "kaput" in data["error"]["detail"]
    assert env.call("GET", "/api/nothing")[0] == 404


# ---- acceptance test 10: the decision tree panel data -------------------------


@pytest.fixture
def tree_env(env: Env, tmp_path: Path) -> Env:
    copy = tmp_path / "tree.yaml"
    shutil.copy(schema_mod.DATA_DIR / "decision_tree.yaml", copy)
    env.app.tree_store.path = copy
    env.app.tree_store.reload()
    env.load_cache(build())
    env.tree_path = copy  # type: ignore[attr-defined]
    return env


def test_acceptance_10_reload_changes_the_panel_and_data_changes_the_path(tree_env: Env) -> None:
    env = tree_env
    first = env.get("/api/trees")["trees"]["system_design"]
    assert first["highlighted"] and first["leaf"]["label"] == "Bạn đang ở đây"
    assert first["questions"][0]["q"].startswith("Mọi yêu cầu đã có mã R")
    leaf_before = (first["leaf"]["index"], first["leaf"]["answer"])

    path = env.tree_path  # type: ignore[attr-defined]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Mọi yêu cầu đã có mã R và mức Bắt buộc / Mong muốn?", "Câu hỏi đã đổi tên?"), encoding="utf-8")
    assert env.get("/api/trees")["trees"]["system_design"]["questions"][0]["q"].startswith("Mọi yêu cầu")  # not yet
    assert env.post("/api/trees/reload")[0] == 200
    assert env.get("/api/trees")["trees"]["system_design"]["questions"][0]["q"] == "Câu hỏi đã đổi tên?"

    tables = build()
    tables["cai_dat"] = [{"khoa": "chot_cap_1", "gia_tri": "Có"}, {"khoa": "chot_cap_2", "gia_tri": "Không"}]
    env.load_cache(tables)
    after = env.get("/api/trees")["trees"]["system_design"]
    assert (after["leaf"]["index"], after["leaf"]["answer"]) != leaf_before
    assert (after["leaf"]["index"], after["leaf"]["answer"]) == (4, "no") and after["leaf"]["screen"] == "cay"


def test_bad_tree_file_keeps_the_old_trees(tree_env: Env) -> None:
    env = tree_env
    env.tree_path.write_text("system_design: []\n", encoding="utf-8")  # type: ignore[attr-defined]
    status, data = env.post("/api/trees/reload")
    assert status == 422 and data["error"]["code"] == "tree_file_bad"
    assert env.get("/api/trees")["trees"]["system_design"]["questions"]


def test_designer_tree_is_plain_reference_without_a_node(tree_env: Env) -> None:
    env = tree_env
    plain = env.get("/api/trees")["trees"]["designer"]
    assert plain["highlighted"] is False and plain["leaf"] is None
    lit = env.get("/api/trees", node="N1.2")["trees"]["designer"]
    assert lit["highlighted"] and lit["leaf"]["screen"] == "nut"
    assert lit["leaf"]["do"].startswith("Viết thông số")  # R6 is allocated to N1.2 but has no specification
    done = env.get("/api/trees", node="N1.1")["trees"]["designer"]
    assert done["leaf"]["index"] != lit["leaf"]["index"]  # a different node, a different place in the tree


def test_engineer_tree_follows_drafts(tree_env: Env) -> None:
    env = tree_env
    env.set_identity("binh", "engineer")
    assert env.get("/api/trees")["trees"]["engineer"]["leaf"]["index"] != 0
    env.draft("yeu_cau", {"ma_yc": "R7", "mo_ta": "a", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    leaf = env.get("/api/trees")["trees"]["engineer"]["leaf"]
    assert leaf["index"] == 0 and leaf["screen"] == "commit"


def test_tree_js_is_pure_svg_and_fits_360(tmp_path: Path) -> None:
    js = (UI_DIR / "tree.js").read_text(encoding="utf-8")
    assert "createElementNS" in js and "const W = 340" in js  # drawn in a 340 unit wide viewBox
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "--panel-w: 360px" in css and "--strip-w" in css


# ---- acceptance test 15: only the Teable host is contacted --------------------


def test_acceptance_15_only_the_teable_host_connects(http: tuple[server.RunningServer, Env], monkeypatch: pytest.MonkeyPatch) -> None:
    running, env = http
    connects: list[tuple[Any, ...]] = []
    resolved: list[str] = []
    real_connect, real_connect_ex, real_gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def spy_connect(self: socket.socket, address: Any) -> Any:
        connects.append(tuple(address) if isinstance(address, (tuple, list)) else (address,))
        return real_connect(self, address)

    def spy_connect_ex(self: socket.socket, address: Any) -> Any:
        connects.append(tuple(address) if isinstance(address, (tuple, list)) else (address,))
        return real_connect_ex(self, address)

    def spy_gai(host: Any, *args: Any, **kwargs: Any) -> Any:
        resolved.append(str(host))
        return real_gai(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", spy_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", spy_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", spy_gai)

    headers = {server.SESSION_HEADER: env.app.session, "Content-Type": "application/json"}

    def post(path: str, body: dict[str, Any]) -> Any:
        status, raw = fetch(running, path, headers=headers, data=json.dumps(body).encode())
        return status, json.loads(raw)

    assert fetch(running, "/")[0] == 200
    assert fetch(running, "/api/state?force=1", headers=headers)[0] == 200
    assert post("/api/refresh", {})[0] == 200
    assert post("/api/draft", {"table": "yeu_cau", "fields": {"ma_yc": "R1", "mo_ta": "a", "muc": "Bắt buộc",
                                                              "trang_thai": "Nháp"}})[0] == 200
    assert post("/api/commit", {})[0] == 200
    for path in ("/api/trees", "/api/overview", "/api/rows?table=yeu_cau", "/api/tree_nodes", "/api/alloc"):
        assert fetch(running, path, headers=headers)[0] == 200

    teable_port = int(env.fake.url.rsplit(":", 1)[1])
    assert connects, "the spy saw no connection at all"
    allowed = {("127.0.0.1", teable_port), ("127.0.0.1", running.port)}
    stray = [c for c in connects if (c[0], c[1]) not in allowed]
    assert not stray, f"connections outside Teable and the UI server: {stray}"
    assert any(c[1] == teable_port for c in connects), "the Teable client never connected"
    assert set(resolved) <= {"127.0.0.1", "localhost"}, f"unexpected name lookups: {resolved}"


def test_only_teable_client_imports_an_http_library() -> None:
    base = Path(server.__file__).parent
    for name in ("server.py", "main.py", "platform.py"):
        text = (base / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(httpx|requests|urllib\.request|http\.client|aiohttp)\b", text, re.M), name
    assert "import httpx" in (base / "teable_client.py").read_text(encoding="utf-8")


def test_platform_is_the_only_place_with_os_branches() -> None:
    base = Path(server.__file__).parent
    for name in ("server.py", "main.py"):
        text = (base / name).read_text(encoding="utf-8")
        assert "sys.platform" not in text and "os.name" not in text and "platform.system" not in text, name


# ---- entry points -------------------------------------------------------------


def test_ui_javascript_parses_when_node_is_available() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the JavaScript was not syntax-checked")
    import subprocess

    for name in ("app.js", "tree.js"):
        result = subprocess.run([node, "--check", str(UI_DIR / name)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_smoke_script_runs() -> None:
    import subprocess
    import sys

    root = Path(server.__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "smoke.py")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "smoke ok" in result.stdout


def test_main_wires_bootstrap_and_browser_flag() -> None:
    from t3desk import main as main_mod

    parser = main_mod.build_parser()
    assert parser.parse_args(["--browser"]).browser is True
    assert parser.parse_args(["bootstrap", "--url", "http://x", "--base-id", "bse1"]).command == "bootstrap"
    assert parser.parse_args([]).command is None


def test_browser_flag_serves_the_ui_to_the_default_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from t3desk import main as main_mod
    from t3desk import platform

    opened: list[str] = []
    seen: list[int] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        seen.append(urllib.request.urlopen(url, timeout=10).status)  # the UI really answers while the app runs
        return True

    def stop(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setenv(platform.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(platform, "open_in_browser", fake_open)
    monkeypatch.setattr(time, "sleep", stop)
    assert main_mod.run_app(True) == 0
    assert opened and opened[0].startswith("http://127.0.0.1:") and seen == [200]
    assert (tmp_path / "t3desk.log").exists()  # one rotating log file in the config folder


def test_native_window_is_used_when_pywebview_is_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    from t3desk import main as main_mod
    from t3desk import platform

    calls: list[tuple[str, Any]] = []
    fake = types.ModuleType("webview")
    fake.create_window = lambda title, url, **kw: calls.append(("window", url))  # type: ignore[attr-defined]
    fake.start = lambda: calls.append(("start", None))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setenv(platform.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(platform, "window_available", lambda: True)
    assert main_mod.run_app(False) == 0
    assert [c[0] for c in calls] == ["window", "start"] and calls[0][1].startswith("http://127.0.0.1:")


def test_window_failure_falls_back_to_the_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import time
    import types

    from t3desk import main as main_mod
    from t3desk import platform

    fake = types.ModuleType("webview")
    fake.create_window = lambda *a, **k: None  # type: ignore[attr-defined]

    def broken() -> None:
        raise RuntimeError("no web view on this machine")

    fake.start = broken  # type: ignore[attr-defined]
    opened: list[str] = []
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setenv(platform.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(platform, "window_available", lambda: True)
    monkeypatch.setattr(platform, "open_in_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert main_mod.run_app(False) == 0 and opened


def test_dialogs_never_cover_the_decision_tree_panel() -> None:
    """The panel stays on top: the overlay stops at the panel edge for every panel width."""
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "#modal-root .overlay { position: fixed; inset: 0 var(--panel-w) 0 0;" in css
    assert 'data-panel="strip"]) #modal-root .overlay { right: var(--strip-w); }' in css
    assert 'data-panel="wide"]) #modal-root .overlay { right: 560px; }' in css
    assert re.search(r"#panel \{ z-index: 4\d;", css)


def test_trees_payload_carries_help_and_glossary(env: Env) -> None:
    data = env.get("/api/trees")
    assert all("help" in q for q in data["trees"]["system_design"]["questions"])
    assert data["trees"]["system_design"]["questions"][5]["help"]
    assert any(g["term"] == "Giá trị phân bổ" for g in data["guide"])
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "drawHelp" in js and 'id="tree-help"' in (UI_DIR / "index.html").read_text(encoding="utf-8")
