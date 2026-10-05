"""Plugins: acceptance tests 11, 12, 13, 14 of docs/REQUIREMENTS.md section 12, plus the api edges.

fake_hermes.py is UNVERIFIED (no Hermes API reference exists); the mcp_tool tests use a fake session.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fake_hermes import TOKEN, FakeHermes
from fixtures import pressure_tank
from t3desk import plugins_api as pa
from t3desk import rfq as rfq_mod
from t3desk import schema as schema_mod
from t3desk.commit import COMMITTED, CONFLICT, Committer
from t3desk.store import Store

REPO = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 5)


# ---------------------------------------------------------------- helpers

class Confirmer:
    """A confirm hook that records every preview and answers from a script."""

    def __init__(self, answer: Any = True):
        self.answer = answer
        self.previews: list[pa.SendPreview] = []

    def __call__(self, preview: pa.SendPreview) -> Any:
        self.previews.append(preview)
        return self.answer


def write_plugin(root: Path, pid: str, py: str, yaml_text: str | None = None) -> Path:
    folder = root / pid
    folder.mkdir(parents=True)
    (folder / "plugin.yaml").write_text(yaml_text or textwrap.dedent(f"""
        id: {pid}
        name: Test {pid}
        version: 0.0.1
        hosts: ["allowed.invalid"]
        writes: [rfq]
        actions:
          - {{id: go, label: Go, screens: [nut.current]}}
        events: [on_start, after_commit]
    """), encoding="utf-8")
    (folder / "plugin.py").write_text(textwrap.dedent(py), encoding="utf-8")
    return folder


@pytest.fixture
def make_app(fake_teable, bootstrapped, make_client, schema, tmp_path) -> Callable[..., SimpleNamespace]:
    """make_app("A", dirs=[...]) -> a separate app: own SQLite, client, Committer and PluginHost."""
    stores: list[Store] = []

    def factory(name: str = "A", *, dirs: list[Path] | None = None, confirm: Any = None) -> SimpleNamespace:
        store = Store(tmp_path / f"{name}.sqlite")
        stores.append(store)
        client = make_client(name)
        committer = Committer(client, store, schema, bootstrapped["table_ids"])
        host = pa.PluginHost(
            store, schema, user=name, plugin_dirs=dirs if dirs is not None else [REPO / "plugins"],
            data_dir=tmp_path / f"{name}_data", confirm=confirm, today=lambda: TODAY, keyring_module=None,
        )
        return SimpleNamespace(name=name, store=store, client=client, committer=committer, host=host,
                               table_ids=bootstrapped["table_ids"])

    yield factory
    for store in stores:
        store.close()


def seed_tank(fake, client, table_ids, edit: Callable[[dict[str, list[dict[str, Any]]]], None] | None = None) -> None:
    """Load the pressure-tank fixture into the fake Teable (cai_dat rows are updated in place)."""
    tables = pressure_tank.build()
    if edit:
        edit(tables)
    for table, rows in tables.items():
        if table == "cai_dat":
            existing = {r["fields"]["khoa"]: r["id"] for r in fake.records("cai_dat")}
            for row in rows:
                if row["khoa"] in existing:
                    client.update_record(table_ids["cai_dat"], existing[row["khoa"]], {"gia_tri": row["gia_tri"]})
                else:
                    fake.seed("cai_dat", row)
            continue
        for row in rows:
            fake.seed(table, {k: v for k, v in row.items() if v is not None})


def distinctive_money(tables: dict[str, list[dict[str, Any]]]) -> None:
    for row in tables["ung_vien"]:
        row["gia_cong_bo"] = 123456.0
    for row in tables["mua_hang"]:
        row["don_gia_bao"] = 987654.0
    for row in tables["cai_dat"]:
        if row["khoa"] == "so_uv_toi_da":
            row["gia_tri"] = "5"
    tables["cai_dat"].append({"khoa": "ngan_sach_tr", "gia_tri": "7777777"})


def enable(app: SimpleNamespace, *ids: str) -> None:
    for pid in ids:
        app.host.set_enabled(pid, True)
    app.host.start()


def refresh(app: SimpleNamespace) -> None:
    app.committer.refresh_cache()


# ---------------------------------------------------------------- manifest

def test_manifest_accepts_shipped_plugins(schema):
    for pid in ("hermes_skill", "mcp_tool", "task_outbox"):
        import yaml

        raw = yaml.safe_load((REPO / "plugins" / pid / "plugin.yaml").read_text(encoding="utf-8"))
        manifest = pa.parse_manifest(raw, schema_mod.table_keys(schema))
        assert manifest.id == pid and manifest.actions


@pytest.mark.parametrize("patch,needle", [
    ({"id": "Bad Id"}, "id"),
    ({"hosts": ["http://x.invalid/path"]}, "bad host"),
    ({"hosts": ["{config:nope}"]}, "unknown config key"),
    ({"events": ["on_boot"]}, "unknown event"),
    ({"actions": [{"id": "go", "screens": ["nodot"]}]}, "bad screen"),
    ({"actions": [{"id": "go", "screens": ["nut.current"], "roles": ["boss"]}]}, "unknown role"),
    ({"writes": ["nope"]}, "unknown table"),
    ({"config": [{"key": "a"}, {"key": "a"}]}, "duplicate"),
])
def test_manifest_rejects_bad_input(patch, needle, schema):
    raw = {"id": "ok_plugin", "name": "n", "version": "1", "actions": [{"id": "go", "screens": ["nut.current"]}]}
    raw.update(patch)
    with pytest.raises(pa.ManifestError) as err:
        pa.parse_manifest(raw, schema_mod.table_keys(schema))
    assert needle in str(err.value)


# ---------------------------------------------------------------- acceptance 11

def test_11_empty_plugins_folder_app_starts_and_commits(make_app, tmp_path):
    app = make_app("A", dirs=[tmp_path / "empty_plugins"])
    app.host.start()
    assert app.host.list_plugins() == []
    app.store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R1", "mo_ta": "x", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    report = app.committer.commit()
    assert report.ok
    app.host.after_commit(report)  # nothing listens; must not raise


def test_11_plugin_raising_on_load_is_disabled_listed_and_commit_works(make_app, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "boom_load", 'raise RuntimeError("cannot start")\n')
    write_plugin(root, "boom_register", "def register(api):\n    raise ValueError('bad register')\n")
    write_plugin(root, "no_register", "x = 1\n")
    write_plugin(root, "good", "def register(api):\n    pass\n")
    (root / "bad_manifest").mkdir()
    (root / "bad_manifest" / "plugin.yaml").write_text("id: BAD\n", encoding="utf-8")
    (root / "bad_manifest" / "plugin.py").write_text("def register(api): pass\n", encoding="utf-8")
    app = make_app("A", dirs=[root])
    app.host.discover()
    for pid in ("boom_load", "boom_register", "no_register", "good"):
        app.host.set_enabled(pid, True)
    app.host.start()

    listed = {p["id"]: p for p in app.host.list_plugins()}
    assert listed["good"]["state"] == "enabled"
    assert "cannot start" in listed["boom_load"]["error"] and listed["boom_load"]["state"] == "failed"
    assert "bad register" in listed["boom_register"]["error"]
    assert "register" in listed["no_register"]["error"]
    assert any(p["state"] == "failed" and "manifest" in p["error"] for p in listed.values() if p["id"] != "good")
    assert len(app.host.failed()) == 4

    app.store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R1", "mo_ta": "x", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    report = app.committer.commit()
    assert [r.status for r in report.results] == [COMMITTED]


def test_11_plugin_raising_in_event_or_action_is_disabled_and_never_blocks_commit(make_app, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "bad_events", """
        def register(api):
            api.on("on_start", lambda: 1 / 0)
            api.on("after_commit", lambda changes: (_ for _ in ()).throw(RuntimeError("after_commit exploded")))
            api.action("go", lambda payload: [][1])
    """)
    app = make_app("A", dirs=[root])
    app.host.set_enabled("bad_events", True)
    app.host.discover()
    app.host.start()  # on_start raises inside the plugin
    assert app.host.plugins["bad_events"].state == "failed"
    assert app.host.run_action("bad_events", "go").status == "unknown"

    app.host.plugins["bad_events"].state = "available"  # reload to hit after_commit and action paths
    app.host.load_all()
    app.store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R2", "mo_ta": "x", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    report = app.committer.commit()
    app.host.after_commit(report)
    info = app.host.plugins["bad_events"]
    assert report.ok and info.state == "failed"
    assert app.host.list_plugins()[0]["error"]
    app.host.plugins["bad_events"].state = "available"
    app.host.load_all()
    assert app.host.run_action("bad_events", "go").status == "error"
    assert "IndexError" in app.host.plugins["bad_events"].error


def test_enabled_state_is_per_machine_and_off_by_default(make_app, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "good", "def register(api):\n    api.log('registered')\n")
    a = make_app("A", dirs=[root])
    a.host.start()
    assert a.host.plugins["good"].state == "available" and not a.host.plugins["good"].enabled
    a.host.set_enabled("good", True)
    b = make_app("B", dirs=[root])
    b.host.start()
    assert b.host.plugins["good"].state == "available"  # B did not enable it
    a.host.start()
    assert a.host.plugins["good"].state == "enabled"


def test_user_config_folder_is_searched_too(make_app, tmp_path):
    shipped, user = tmp_path / "shipped", tmp_path / "user_cfg"
    write_plugin(shipped, "one", "def register(api): pass\n")
    write_plugin(user, "two", "def register(api): pass\n")
    app = make_app("A", dirs=[shipped, user])
    assert {i.id for i in app.host.discover()} == {"one", "two"}


# ---------------------------------------------------------------- acceptance 12

def _net_plugin(tmp_path, hosts: str):
    root = tmp_path / "plugins"
    write_plugin(root, "net", """
        def register(api):
            api.action("go", lambda payload: api.http("GET", payload).text)
    """, f"""
id: net
name: Net
version: 1
hosts: {hosts}
actions:
  - {{id: go, label: Go, screens: [nut.current]}}
""")
    return root


def test_12_host_not_in_manifest_is_refused_and_nothing_is_sent(make_app, tmp_path):
    with FakeHermes() as hermes:
        app = make_app("A", dirs=[_net_plugin(tmp_path, '["allowed.invalid"]')])
        enable(app, "net")
        api = app.host._apis["net"]
        for url in (hermes.url + "/v1/runs/x", "http://allowed.invalid@127.0.0.1:1/", "ftp://allowed.invalid/",
                    "http://allowed.invalid.evil.example/"):
            with pytest.raises(pa.HostNotAllowed):
                api.http("GET", url)
        assert hermes.requests == []
        assert any("refused" in e["result"] for e in app.host.audit_entries())
        result = app.host.run_action("net", "go", hermes.url + "/v1/runs/x")
        assert result.status == "error" and app.host.plugins["net"].state == "failed"
        assert hermes.requests == []


def test_12_port_must_match_when_manifest_names_one(make_app, tmp_path):
    with FakeHermes() as hermes:
        port = hermes.host.split(":")[1]
        app = make_app("A", dirs=[_net_plugin(tmp_path, f'["127.0.0.1:{port}"]')])
        enable(app, "net")
        api = app.host._apis["net"]
        assert api.http("GET", hermes.url + "/nothing", headers={"Authorization": f"Bearer {TOKEN}"}).status == 404
        with pytest.raises(pa.HostNotAllowed):
            api.http("GET", "http://127.0.0.1:1/x")


def test_http_network_failure_is_a_clear_plugin_error(make_app, tmp_path):
    app = make_app("A", dirs=[_net_plugin(tmp_path, '["127.0.0.1"]')])
    enable(app, "net")
    with pytest.raises(pa.PluginHttpError) as err:
        app.host._apis["net"].http("GET", "http://127.0.0.1:9/")
    assert "failed" in str(err.value)


# ---------------------------------------------------------------- preview, audit, secrets

def test_preview_shows_exact_payload_and_host_decline_sends_nothing(make_app, tmp_path):
    with FakeHermes() as hermes:
        confirm = Confirmer(False)
        app = make_app("A", dirs=[_net_plugin(tmp_path, '["127.0.0.1"]')], confirm=confirm)
        enable(app, "net")
        api = app.host._apis["net"]
        with app.host._in_action("go"):
            with pytest.raises(pa.SendDeclined):
                api.http("POST", hermes.url + "/v1/skills/x/runs", {"a": 1}, record_ids=["RFQ-001"])
        assert hermes.requests == []
        preview = confirm.previews[0]
        assert preview.payload == {"a": 1} and preview.host == hermes.host and preview.method == "POST"
        assert app.host.audit_entries()[-1]["result"] == "declined by user"


def test_declined_action_is_reported_not_treated_as_plugin_failure(make_app, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "send", """
        def register(api):
            api.action("go", lambda p: api.http("POST", "http://allowed.invalid/x", {"k": 1}))
    """)
    app = make_app("A", dirs=[root], confirm=Confirmer(False))
    enable(app, "send")
    result = app.host.run_action("send", "go")
    assert result.status == "declined" and app.host.plugins["send"].state == "enabled"


def test_skip_preview_for_rest_of_session_is_per_action(make_app, tmp_path):
    with FakeHermes() as hermes:
        confirm = Confirmer(pa.SESSION)
        app = make_app("A", dirs=[_net_plugin(tmp_path, '["127.0.0.1"]')], confirm=confirm)
        enable(app, "net")
        api = app.host._apis["net"]
        with app.host._in_action("go"):
            api.http("POST", hermes.url + "/v1/skills/s/runs", {"n": 1}, headers={"Authorization": f"Bearer {TOKEN}"})
            api.http("POST", hermes.url + "/v1/skills/s/runs", {"n": 2}, headers={"Authorization": f"Bearer {TOKEN}"})
        assert len(confirm.previews) == 1 and len(hermes.requests) == 2
        with app.host._in_action("other"):
            api.http("POST", hermes.url + "/v1/skills/s/runs", {"n": 3}, headers={"Authorization": f"Bearer {TOKEN}"})
        assert len(confirm.previews) == 2


def test_audit_log_has_fields_but_no_secret_or_payload(make_app, fake_teable, tmp_path):
    with FakeHermes() as hermes:
        confirm = Confirmer(True)
        app = make_app("A", confirm=confirm)
        app.host.set_enabled("hermes_skill", True)
        app.host.discover()
        app.host.set_config("hermes_skill", "base_url", hermes.url)
        app.host.set_secret("hermes_skill", "token", TOKEN)
        app.host.load_all()
        api = app.host._apis["hermes_skill"]
        with app.host._in_action("tao_rfq"):
            api.http("POST", hermes.url + "/v1/skills/rfq/runs", {"secret_text": "payload-body"},
                     headers={"Authorization": f"Bearer {TOKEN}"}, record_ids=["RFQ-009"])
        api.log("calling with", TOKEN)
        api.notify(f"token was {TOKEN}")
        entry = app.host.audit_entries()[-1]
        assert {"time", "user", "plugin", "action", "host", "record_ids", "result"} <= set(entry)
        assert entry["plugin"] == "hermes_skill" and entry["user"] == "A" and entry["record_ids"] == ["RFQ-009"]
        assert entry["host"].startswith(hermes.host) and entry["result"] == "HTTP 200"
        leaks = [app.host.audit_path.read_text(encoding="utf-8"), app.host.log_path.read_text(encoding="utf-8"),
                 Path(app.store.path).read_bytes().decode("latin-1"), " ".join(t for _, t in app.host.notifications)]
        for text in leaks:
            assert TOKEN not in text
        assert "payload-body" not in leaks[0]
        assert app.host.get_secret("hermes_skill", "token") == TOKEN
        with pytest.raises(pa.WriteNotAllowed):
            app.host.get_config("hermes_skill", "token")  # secrets only through api.secret
        with pytest.raises(KeyError):
            app.host.get_secret("hermes_skill", "base_url")


# ---------------------------------------------------------------- draft api: the only write path

def test_draft_api_validates_scopes_and_never_touches_teable(make_app, fake_teable, tmp_path):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    app = make_app("A")
    enable(app, "hermes_skill")
    refresh(app)
    api = app.host._apis["hermes_skill"]
    before = fake_teable.snapshot()
    with pytest.raises(pa.WriteNotAllowed):
        api.draft_create("yeu_cau", {"ma_yc": "R9", "mo_ta": "x", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    with pytest.raises(pa.DraftInvalid):
        api.draft_create("rfq", {"ma_rfq": "bad id", "loai": "RFQ"})
    with pytest.raises(pa.DraftInvalid):  # unknown candidate code
        api.draft_create("rfq", {"ma_rfq": "RFQ-001", "loai": "RFQ", "ds_ma_uv": "UV-999", "trang_thai": "Nháp"})
    draft = api.draft_create("rfq", {"ma_rfq": "RFQ-001", "loai": "RFQ", "ds_ma_uv": "UV-002", "trang_thai": "Nháp"})
    with pytest.raises(pa.DraftExists):
        api.draft_create("rfq", {"ma_rfq": "RFQ-001", "loai": "RFQ", "trang_thai": "Nháp"})
    assert api.draft_update("rfq", "RFQ-001", {"trang_thai": "Nháp"}) is None  # no real change
    merged = api.draft_update("rfq", "RFQ-001", {"ghi_chu": "n"})
    assert merged.id == draft.id and merged.fields["ghi_chu"] == "n"
    with pytest.raises(pa.RecordNotFound):
        api.draft_update("rfq", "RFQ-404", {"ghi_chu": "n"})
    assert fake_teable.snapshot() == before  # nothing reached Teable
    assert app.store.count_drafts() == 1
    assert api.draft_discard("rfq", "RFQ-001") and app.store.count_drafts() == 0
    assert not hasattr(api, "commit") and not hasattr(api, "client")


def test_read_is_a_copy_and_rules_run_on_the_cache(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    app = make_app("A")
    enable(app, "task_outbox")
    refresh(app)
    api = app.host._apis["task_outbox"]
    rows = api.read("nut", {"ma_nut": "N1.1"})
    assert rows[0]["ten"] == "Hydrophone"
    rows[0]["ten"] = "changed"
    assert api.read("nut", {"ma_nut": "N1.1"})[0]["ten"] == "Hydrophone"
    assert api.rules().next_action("N1.1").code == "done"
    assert api.rules().counters()["pairs_missing_spec"] == 1


def test_jobs_poll_and_status_bar(make_app, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "slow", """
        def register(api):
            state = {"n": 0}
            def poll(job):
                state["n"] += 1
                api.job_update(job.id, message=f"poll {state['n']}")
                if state["n"] == 2:
                    api.job_update(job.id, state="done")
            api.on("on_job_poll", poll)
            api.action("go", lambda p: api.job_start("slow job"))
    """, """
id: slow
name: Slow
version: 1
actions:
  - {id: go, label: Go, screens: [nut.current]}
events: [on_job_poll]
""")
    app = make_app("A", dirs=[root])
    enable(app, "slow")
    job_id = app.host.run_action("slow", "go").value
    app.host.poll_jobs()
    assert app.host.status_bar_jobs() == ["slow job: poll 1"]
    app.host.poll_jobs()
    assert app.host.jobs[job_id].state == "done" and app.host.status_bar_jobs() == []


# ---------------------------------------------------------------- RFQ payload (unit)

def _analysis(edit=None):
    tables = pressure_tank.build()
    distinctive_money(tables)
    if edit:
        edit(tables)
    from t3desk import rules
    return rules.analyse(tables, rules.Context(today=TODAY, user="an"))


def test_rfq_payload_has_the_9_2_shape_and_no_price_budget_or_score():
    a = _analysis()
    payload = rfq_mod.build_payload(a, kind="RFQ", ma_rfq="RFQ-003", requested_by="an", reply_by="2026-10-20",
                                    vendor="Hãng", ma_uv=["UV-002"])
    assert list(payload) == ["kind", "ma_rfq", "project", "requested_by", "language", "reply_by", "need_by",
                             "vendor", "items", "node"]
    assert payload["project"] == "Bể áp lực" and payload["need_by"] == "2027-03-01" and payload["node"] is None
    item = payload["items"][0]
    assert (item["ma_uv"], item["ma_nut"], item["ten_nut"], item["so_luong"]) == ("UV-002", "N1.1", "Hydrophone", 2)
    assert {"ma_ts": "TS-001", "thong_so": "Độ nhạy", "yeu_cau": "≥ -180 u", "muc": "Bắt buộc"} in item["specs"]
    assert any(s["yeu_cau"] == "10 - 20000 u" for s in item["specs"])
    text = json.dumps(payload, ensure_ascii=False)
    for secret in ("123456", "987654", "7777777"):
        assert secret not in text
    assert rfq_mod.forbidden_paths(payload) == []
    assert "UV-001" not in text and "UV-003" not in text  # other candidates stay out


def test_rfp_payload_carries_node_requirements_and_specs_with_empty_items():
    a = _analysis()
    payload = rfq_mod.build_payload(a, kind="RFP", ma_rfq="RFP-001", requested_by="an", reply_by=None,
                                    ma_nut="N1.1")
    assert payload["items"] == [] and payload["node"]["ma_nut"] == "N1.1"
    assert [r["ma_yc"] for r in payload["node"]["yeu_cau"]] == ["R1", "R2"]
    assert {"ma_yc", "mo_ta", "tieu_chi_nghiem_thu"} == set(payload["node"]["yeu_cau"][0])
    assert [s["ma_ts"] for s in payload["node"]["specs"]] == ["TS-001", "TS-002"]
    assert rfq_mod.forbidden_paths(payload) == []
    budget_node = rfq_mod.build_payload(a, kind="RFP", ma_rfq="RFP-002", requested_by="an", reply_by=None, ma_nut="N2.1")
    assert "7777777" not in json.dumps(budget_node) and rfq_mod.forbidden_paths(budget_node) == []


def test_forbidden_content_guard_catches_price_budget_score_keys():
    bad = {"items": [{"gia_cong_bo": 1}], "x": {"ngan_sach_tr": 2, "diem_ky_thuat": 3, "don_gia_bao": 4,
                                                  "budget": 5, "price": 6, "score": 7}}
    assert len(rfq_mod.forbidden_paths(bad)) == 7
    with pytest.raises(rfq_mod.ForbiddenContent):
        rfq_mod.assert_clean(bad)
    assert rfq_mod.forbidden_paths({"tieu_chi_nghiem_thu": "x", "language": "vi", "ma_rfq": "RFQ-1"}) == []


@pytest.mark.parametrize("kwargs", [
    {"kind": "RFQ"}, {"kind": "RFP"}, {"kind": "RFX", "ma_nut": "N1"},
    {"kind": "RFQ", "ma_uv": ["UV-404"]}, {"kind": "RFP", "ma_nut": "N404"},
])
def test_rfq_builder_rejects_incomplete_requests(kwargs):
    with pytest.raises(rfq_mod.RfqError):
        rfq_mod.build_payload(_analysis(), ma_rfq="RFQ-001", requested_by="an", reply_by=None, **kwargs)


def test_requirement_text_forms():
    f = rfq_mod.requirement_text
    assert f({"gia_tri_max": 5, "don_vi": "kg"}) == "≤ 5 kg"
    assert f({"gia_tri_min": 10, "gia_tri_max": 20, "don_vi": "MHz"}) == "10 - 20 MHz"
    assert f({"kieu": "Định tính", "mong_doi": "IP68"}) == "IP68"


# ---------------------------------------------------------------- acceptance 13

def _hermes_app(make_app, hermes, confirm):
    app = make_app("A", confirm=confirm)
    app.host.set_enabled("hermes_skill", True)
    app.host.discover()
    app.host.set_config("hermes_skill", "base_url", hermes.url)
    app.host.set_secret("hermes_skill", "token", TOKEN)
    app.host.start()
    assert app.host.plugins["hermes_skill"].state == "enabled", app.host.plugins["hermes_skill"].error
    return app


def test_13_rfq_flow_against_fake_hermes_ends_with_committed_rfq_in_da_tao(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids, distinctive_money)
    with FakeHermes(polls_until_done=2) as hermes:
        confirm = Confirmer(True)
        app = _hermes_app(make_app, hermes, confirm)
        refresh(app)

        start = rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-002"], vendor="Hãng", reply_by="2026-10-20")
        assert start.ma_rfq == "RFQ-001"
        draft = app.store.list_drafts("rfq")[0]
        assert draft.fields["trang_thai"] == "Nháp" and draft.fields["ds_ma_uv"] == "UV-002"

        result = app.host.run_action("hermes_skill", "tao_rfq", start.payload)
        assert result.status == "ok", result.error
        # the preview showed the exact payload and the target host, and it is clean
        preview = confirm.previews[0]
        assert preview.payload == start.payload and preview.host == hermes.host
        text = json.dumps(preview.payload, ensure_ascii=False)
        assert rfq_mod.forbidden_paths(preview.payload) == []
        for secret in ("123456", "987654", "7777777"):
            assert secret not in text
        assert hermes.runs["run-0001"]["payload"] == start.payload and hermes.runs["run-0001"]["skill"] == "rfq"
        # the draft is now Đang tạo with the run reference
        draft = app.store.list_drafts("rfq")[0]
        assert draft.fields["trang_thai"] == "Đang tạo" and draft.fields["ma_tac_vu_ngoai"] == "run-0001"
        assert draft.fields["plugin"] == "hermes_skill"
        assert app.host.status_bar_jobs()

        app.host.poll_jobs()  # still running
        assert app.store.list_drafts("rfq")[0].fields["trang_thai"] == "Đang tạo"
        app.host.poll_jobs()  # done
        assert app.host.status_bar_jobs() == []
        draft = app.store.list_drafts("rfq")[0]
        assert draft.fields["trang_thai"] == "Đã tạo" and draft.fields["link_tai_lieu"] == hermes.link

        report = app.committer.commit()
        assert [r.status for r in report.results] == [COMMITTED], report.lines()
        stored = fake_teable.records("rfq")[0]["fields"]
        assert stored["ma_rfq"] == "RFQ-001" and stored["trang_thai"] == "Đã tạo"
        assert stored["link_tai_lieu"] == hermes.link and stored["ma_tac_vu_ngoai"] == "run-0001"
        # nothing left the machine except to Hermes, and the token never reached its request log
        assert {r["method"] for r in hermes.requests} == {"POST", "GET"}
        assert TOKEN not in json.dumps(hermes.requests)
        audit = app.host.audit_entries()
        assert audit[0]["record_ids"] == ["RFQ-001", "UV-002"] and audit[0]["plugin"] == "hermes_skill"


def test_13_user_declining_the_preview_sends_nothing_and_keeps_the_draft_in_nhap(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    with FakeHermes() as hermes:
        app = _hermes_app(make_app, hermes, Confirmer(False))
        refresh(app)
        start = rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-002"])
        assert app.host.run_action("hermes_skill", "tao_rfq", start.payload).status == "declined"
        assert hermes.requests == [] and app.store.list_drafts("rfq")[0].fields["trang_thai"] == "Nháp"


def test_13_failed_hermes_run_returns_draft_to_nhap_with_note(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    with FakeHermes(polls_until_done=1, fail=True) as hermes:
        app = _hermes_app(make_app, hermes, Confirmer(True))
        refresh(app)
        start = rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-002"])
        app.host.run_action("hermes_skill", "tao_rfq", start.payload)
        app.host.poll_jobs()
        draft = app.store.list_drafts("rfq")[0]
        assert draft.fields["trang_thai"] == "Nháp" and "skill crashed" in draft.fields["ghi_chu"]
        assert any("failed" in t for _, t in app.host.notifications)


def test_13_rfp_flow_uses_rfp_skill_and_empty_items(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    with FakeHermes(polls_until_done=1) as hermes:
        app = _hermes_app(make_app, hermes, Confirmer(True))
        refresh(app)
        start = rfq_mod.start_rfq(app.host.core, kind="RFP", ma_nut="N2.1")
        assert start.ma_rfq == "RFP-001" and start.payload["items"] == []
        app.host.run_action("hermes_skill", "tao_rfp", start.payload)
        app.host.poll_jobs()
        assert hermes.runs["run-0001"]["skill"] == "rfp"
        assert app.committer.commit().ok
        assert fake_teable.records("rfq")[0]["fields"]["trang_thai"] == "Đã tạo"


def test_13_non_dat_candidate_needs_an_extra_confirmation(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    app = make_app("A")
    enable(app)
    refresh(app)
    asked: list[Any] = []
    with pytest.raises(rfq_mod.ExtraConfirmationRequired) as err:
        rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-002", "UV-003"])
    assert err.value.candidates[0][0] == "UV-003"
    with pytest.raises(rfq_mod.ExtraConfirmationRequired):
        rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-003"], extra_confirm=lambda c: asked.append(c) or False)
    assert app.store.list_drafts("rfq") == [] and asked
    ok = rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-003"], extra_confirm=lambda c: True)
    assert ok.ma_rfq == "RFQ-001" and len(app.store.list_drafts("rfq")) == 1
    # a passing candidate never asks
    rfq_mod.start_rfq(app.host.core, kind="RFQ", ma_uv=["UV-002"], extra_confirm=lambda c: pytest.fail("asked"))


# ---------------------------------------------------------------- acceptance 14

def _task_app(make_app, name: str):
    app = make_app(name)
    enable(app, "task_outbox")
    assert app.host.plugins["task_outbox"].state == "enabled", app.host.plugins["task_outbox"].error
    refresh(app)
    return app


def _open_unfinished_n11(tables):
    for row in tables["ung_vien"]:
        if row["ma_uv"] == "UV-001":
            row["trang_thai"] = "Ứng viên"
            row.pop("ly_do", None)


def test_14_desired_tasks_from_the_pressure_tank_fixture():
    path = REPO / "plugins" / "task_outbox" / "plugin.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("task_outbox_unit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from t3desk import rules

    tables = pressure_tank.build()
    tables["sai_lech"] = [{"ma_sl": "SL-001", "mo_ta": "Đổi cảm biến", "ma_nut": "N1.2", "nguoi_nhan": "an",
                           "han": "2026-10-09", "trang_thai": "Mở"},
                          {"ma_sl": "SL-002", "mo_ta": "Đã xong", "trang_thai": "Xong"}]
    tables["rfq"] = [{"ma_rfq": "RFQ-001", "loai": "RFQ", "trang_thai": "Đã gửi", "han_tra_loi": "2026-10-01",
                      "nha_cung_cap": "Hãng", "ds_ma_nut": "N1.1"},
                     {"ma_rfq": "RFQ-002", "loai": "RFQ", "trang_thai": "Đã gửi", "han_tra_loi": "2026-10-30"},
                     {"ma_rfq": "RFQ-003", "loai": "RFQ", "trang_thai": "Đã có trả lời", "han_tra_loi": "2026-10-01"}]
    a = rules.analyse(tables, rules.Context(today=TODAY))
    tasks = module.desired_tasks(a, TODAY.isoformat())
    keys = set(tasks)
    assert "CV|buoc|N1.1" not in keys  # Xong: no open task
    assert {"CV|buoc|N1.2", "CV|buoc|N2.1", "CV|buoc|N2.2", "CV|buoc|N3", "CV|buoc|N4", "CV|buoc|N5"} <= keys
    assert "CV|buoc|N1" not in keys and "CV|buoc|N0" not in keys  # only leaves
    assert "CV|cho_nhan|UV-002" in keys
    assert "CV|sai_lech|SL-001" in keys and "CV|sai_lech|SL-002" not in keys
    assert "CV|rfq|RFQ-001" in keys and "CV|rfq|RFQ-002" not in keys and "CV|rfq|RFQ-003" not in keys
    assert "CV|canh_bao|binh" in keys
    assert all(t["trang_thai"] == "Mở" for t in tasks.values())
    assert tasks["CV|sai_lech|SL-001"]["han"] == "2026-10-09"
    assert tasks["CV|buoc|N1.2"]["nguoi_nhan"] == "binh"
    assert all("ma_ngoai" not in t and "dong_bo_luc" not in t for t in tasks.values())
    # same data -> byte-identical rows, whoever computes them
    assert module.desired_tasks(rules.analyse(tables, rules.Context(today=TODAY, user="other")),
                                TODAY.isoformat()) == tasks


def test_14_two_apps_on_same_data_produce_one_row_per_task(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    a, b = _task_app(make_app, "A"), _task_app(make_app, "B")
    assert a.host.run_action("task_outbox", "rebuild").status == "ok"
    assert b.host.run_action("task_outbox", "rebuild").status == "ok"
    keys_a = sorted(d.key for d in a.store.list_drafts("cong_viec"))
    assert keys_a == sorted(d.key for d in b.store.list_drafts("cong_viec")) and len(keys_a) >= 7
    assert len(set(keys_a)) == len(keys_a)

    first = a.committer.commit()
    assert all(r.status == COMMITTED for r in first.results), first.lines()
    a.host.after_commit(first)
    second = b.committer.commit()
    assert all(r.status == CONFLICT for r in second.results), second.lines()  # already exists
    b.host.after_commit(second)

    rows = fake_teable.records("cong_viec")
    assert sorted(r["fields"]["ma_cv"] for r in rows) == keys_a  # exactly one row per task
    assert all(r["fields"]["trang_thai"] == "Mở" and r["fields"]["cap_nhat_luc"] for r in rows)
    assert a.store.count_drafts() == 0 and b.store.count_drafts() == 0  # B dropped its duplicates
    assert b.host.plugins["task_outbox"].state == "enabled"

    # nothing changed -> a rebuild on either app drafts nothing
    for app in (a, b):
        refresh(app)
        app.host.run_action("task_outbox", "rebuild")
        assert app.store.count_drafts() == 0


def test_14_leaf_reaching_xong_closes_its_task_and_ma_ngoai_survives(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids, _open_unfinished_n11)
    a = _task_app(make_app, "A")
    a.host.run_action("task_outbox", "rebuild")
    assert any(d.key == "CV|buoc|N1.1" for d in a.store.list_drafts("cong_viec"))
    assert a.committer.commit().ok
    row = next(r for r in fake_teable.records("cong_viec") if r["fields"]["ma_cv"] == "CV|buoc|N1.1")
    assert row["fields"]["trang_thai"] == "Mở"

    # Paperclip claims the task; T3 Desk must never touch these two fields again
    a.client.update_record(a.table_ids["cong_viec"], row["id"], {"ma_ngoai": "PC-77", "dong_bo_luc": "2026-10-04"})
    uv = next(r for r in fake_teable.records("ung_vien") if r["fields"]["ma_uv"] == "UV-001")
    a.client.update_record(a.table_ids["ung_vien"], uv["id"], {"trang_thai": "Chọn", "ly_do": "tốt nhất"})
    refresh(a)
    a.host.run_action("task_outbox", "rebuild")
    updates = [d for d in a.store.list_drafts("cong_viec") if d.key == "CV|buoc|N1.1"]
    assert len(updates) == 1 and updates[0].op == "update"
    assert set(updates[0].fields) <= {"trang_thai", "cap_nhat_luc"} and updates[0].fields["trang_thai"] == "Xong"
    assert not ({"ma_ngoai", "dong_bo_luc"} & set(updates[0].fields))
    report = a.committer.commit()
    assert report.ok, report.lines()
    stored = next(r for r in fake_teable.records("cong_viec") if r["fields"]["ma_cv"] == "CV|buoc|N1.1")["fields"]
    assert stored["trang_thai"] == "Xong"  # closed, not removed
    assert stored["ma_ngoai"] == "PC-77" and stored["dong_bo_luc"].startswith("2026-10-04")

    # an owner change updates only the changed field; ma_ngoai still survives
    node = next(r for r in fake_teable.records("nut") if r["fields"]["ma_nut"] == "N1.2")
    a.client.update_record(a.table_ids["nut"], node["id"], {"phu_trach": "chi"})
    n12 = next(r for r in fake_teable.records("cong_viec") if r["fields"]["ma_cv"] == "CV|buoc|N1.2")
    a.client.update_record(a.table_ids["cong_viec"], n12["id"], {"ma_ngoai": "PC-78"})
    refresh(a)
    a.host.run_action("task_outbox", "rebuild")
    n12_updates = [d for d in a.store.list_drafts("cong_viec") if d.key == "CV|buoc|N1.2"]
    assert len(n12_updates) == 1 and n12_updates[0].fields["nguoi_nhan"] == "chi"
    assert set(n12_updates[0].fields) <= {"nguoi_nhan", "cap_nhat_luc"}
    assert a.committer.commit().ok
    assert next(r for r in fake_teable.records("cong_viec") if r["fields"]["ma_cv"] == "CV|buoc|N1.2")["fields"][
        "ma_ngoai"] == "PC-78"
    assert next(r for r in fake_teable.records("cong_viec") if r["fields"]["ma_cv"] == "CV|buoc|N1.1")["fields"][
        "ma_ngoai"] == "PC-77"


def test_14_api_refuses_ma_ngoai_and_dong_bo_luc_even_if_a_plugin_tries(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    a = _task_app(make_app, "A")
    a.host.run_action("task_outbox", "rebuild")
    assert a.committer.commit().ok
    api = a.host._apis["task_outbox"]
    for field in ("ma_ngoai", "dong_bo_luc"):
        with pytest.raises(pa.WriteNotAllowed):
            api.draft_update("cong_viec", "CV|buoc|N2.1", {field: "x"})
        with pytest.raises(pa.WriteNotAllowed):
            api.draft_create("cong_viec", {"ma_cv": "CV|buoc|ZZ", "nguon": "buoc", "tieu_de": "t", field: "x"})
    assert a.store.count_drafts() == 0


def test_14_task_whose_condition_ends_is_set_xong_never_removed(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    a = _task_app(make_app, "A")
    a.host.run_action("task_outbox", "rebuild")
    assert a.committer.commit().ok
    before = len(fake_teable.records("cong_viec"))
    uv002 = next(r for r in fake_teable.records("ung_vien") if r["fields"]["ma_uv"] == "UV-002")
    a.client.update_record(a.table_ids["ung_vien"], uv002["id"], {"trang_thai": "Loại", "ly_do": "x"})
    refresh(a)
    a.host.run_action("task_outbox", "rebuild")  # UV-002 no longer waits for sourcing
    assert a.committer.commit().ok
    rows = {r["fields"]["ma_cv"]: r["fields"] for r in fake_teable.records("cong_viec")}
    assert len(rows) >= before and rows["CV|cho_nhan|UV-002"]["trang_thai"] == "Xong"


def test_14_paperclip_push_is_skipped_without_config_and_uses_allow_list_with_it(make_app, fake_teable):
    seed_tank(fake_teable, make_app("S").client, make_app("S").table_ids)
    with FakeHermes() as stand_in:  # any local server; the push endpoint is UNVERIFIED
        confirm = Confirmer(True)
        a = make_app("A", confirm=confirm)
        enable(a, "task_outbox")
        refresh(a)
        a.host.run_action("task_outbox", "rebuild")
        assert confirm.previews == [] and stand_in.requests == []  # no config: nothing sent
        a.host.set_config("task_outbox", "paperclip_url", stand_in.url)
        a.host.set_secret("task_outbox", "paperclip_token", "pc-token-1234")
        for d in a.store.list_drafts("cong_viec"):
            a.store.remove_draft(d.id)
        a.host.run_action("task_outbox", "rebuild")
        assert confirm.previews and confirm.previews[0].host == stand_in.host
        pushed = confirm.previews[0].payload["tasks"]
        assert pushed and all("ma_ngoai" not in t and "dong_bo_luc" not in t for t in pushed)
        assert a.host.plugins["task_outbox"].state == "enabled"  # a 401 from the stand-in is not a plugin fault


# ---------------------------------------------------------------- mcp_tool

def _mcp_plugin_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mcp_tool_unit", REPO / "plugins" / "mcp_tool" / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_is_imported_only_inside_functions():
    tree = ast.parse((REPO / "plugins" / "mcp_tool" / "plugin.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    for node in top_level:
        names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
        assert not any(str(n).split(".")[0] == "mcp" for n in names)
    inner = [n for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             for n in ast.walk(f) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("mcp")]
    assert inner  # the import exists, but only inside open_session
    core = [p for p in (REPO / "t3desk").glob("*.py") if "import mcp" in p.read_text(encoding="utf-8")
            or "from mcp" in p.read_text(encoding="utf-8")]
    assert core == []


def test_mcp_template_rendering():
    m = _mcp_plugin_module()
    payload = {"items": [{"hang": "Reson", "model": "TC4013", "so_luong": 2}], "vendor": None, "ma_rfq": "RFQ-001"}
    out = m.render_template({"query": "{{items.0.hang}} {{items.0.model}} {{vendor}}", "n": "{{items.0.so_luong}}",
                             "all": "{{.}}", "lst": ["{{ma_rfq}}", 3], "gone": "{{items.5.x}}"}, payload)
    assert out["query"] == "Reson TC4013" and out["n"] == 2 and out["all"] == payload
    assert out["lst"] == ["RFQ-001", 3] and out["gone"] is None


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(content=[SimpleNamespace(text=f"known about {arguments.get('query')}")])

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="query", description="ask"),
                                      SimpleNamespace(name="put_page", description="")])


def _mcp_app(make_app, confirm, **config):
    app = make_app("A", confirm=confirm)
    app.host.set_enabled("mcp_tool", True)
    app.host.discover()
    for key, value in config.items():
        app.host.set_config("mcp_tool", key, value)
    app.host.start()
    assert app.host.plugins["mcp_tool"].state == "enabled", app.host.plugins["mcp_tool"].error
    session = FakeSession()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(_api):
        yield session

    app.host.plugins["mcp_tool"].module.open_session = fake_open
    return app, session


def test_mcp_lookup_action_previews_calls_tool_and_shows_result_without_writing(make_app):
    confirm = Confirmer(True)
    app, session = _mcp_app(make_app, confirm, command="gbrain", args="serve")
    payload = {"items": [{"hang": "Reson", "model": "TC4013"}], "vendor": "Reson"}
    result = app.host.run_action("mcp_tool", "tra_cuu_boi_canh", payload)
    assert result.status == "ok" and result.value == "known about Reson TC4013 Reson"
    assert session.calls == [("query", {"query": "Reson TC4013 Reson"})]
    assert confirm.previews[0].payload == {"tool": "query", "arguments": {"query": "Reson TC4013 Reson"}}
    assert confirm.previews[0].host == "stdio:gbrain"
    assert app.host.notifications[-1][1].startswith("known about")
    assert app.store.count_drafts() == 0
    assert app.host.audit_entries()[-1]["host"] == "stdio:gbrain"


def test_mcp_declined_preview_calls_nothing_and_unmapped_action_is_a_plugin_error(make_app):
    app, session = _mcp_app(make_app, Confirmer(False), command="gbrain")
    assert app.host.run_action("mcp_tool", "tra_cuu_boi_canh", {}).status == "declined"
    assert session.calls == []
    app2, session2 = _mcp_app(make_app, Confirmer(True), command="gbrain")
    result = app2.host.run_action("mcp_tool", "tao_rfq", {"ma_rfq": "RFQ-001"})  # gbrain tool unknown: unmapped
    assert result.status == "error" and "no tool is mapped" in result.error and session2.calls == []


def test_mcp_custom_mapping_and_tool_listing(make_app):
    mapping = json.dumps({"tao_rfq": {"tool": "make_rfq", "args": {"doc": "{{.}}"}}})
    app, session = _mcp_app(make_app, Confirmer(True), command="gbrain", mappings=mapping)
    app.host.run_action("mcp_tool", "tao_rfq", {"ma_rfq": "RFQ-005"})
    assert session.calls == [("make_rfq", {"doc": {"ma_rfq": "RFQ-005"}})]
    app.host.plugins["mcp_tool"].state = "enabled"
    listed = app.host.run_action("mcp_tool", "liet_ke_cong_cu")
    assert [t["name"] for t in listed.value] == ["query", "put_page"]


def test_mcp_url_transport_obeys_the_host_allow_list(make_app):
    app, _ = _mcp_app(make_app, Confirmer(True), transport="url", url="http://127.0.0.1:8765/mcp")
    api = app.host._apis["mcp_tool"]
    assert api.check_host("http://127.0.0.1:8765/mcp") == "127.0.0.1:8765"
    with pytest.raises(pa.HostNotAllowed):
        api.check_host("http://127.0.0.1:9999/mcp")
    with pytest.raises(pa.HostNotAllowed):
        api.check_host("http://elsewhere.invalid/mcp")


def test_actions_for_screen_and_role_only_lists_loaded_plugins(make_app):
    app = make_app("A")
    enable(app, "hermes_skill", "mcp_tool")
    buttons = {(pid, a.id) for pid, a in app.host.actions_for("mua_hang.selection", "sourcing")}
    assert ("hermes_skill", "tao_rfq") in buttons and ("mcp_tool", "tra_cuu_boi_canh") in buttons
    assert ("hermes_skill", "tao_rfp") not in buttons  # not on that screen
    assert not any(pid == "task_outbox" for pid, _ in buttons)  # not enabled
    assert ("hermes_skill", "tao_rfp") not in {(p, a.id) for p, a in app.host.actions_for("rfq.row", "sourcing")}
