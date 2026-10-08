"""Acceptance tests 1 and 4 (section 12), plus bootstrap behaviour from section 10."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from fake_teable import FakeTeable
from t3desk import schema as schema_mod
from t3desk.bootstrap import BootstrapError, run_bootstrap
from t3desk.main import main as cli_main
from t3desk.teable_client import TeableClient, TeableError, UniqueFlagError

SCRATCH = "zz_scratch_check"


def schema_tables(fake: FakeTeable) -> list[str]:
    return [n for n in fake.table_names() if n != SCRATCH]


# ---- acceptance test 1 -------------------------------------------------------


def test_bootstrap_creates_fifteen_tables_on_empty_base(fake_teable, bootstrapped, schema):
    report = bootstrapped["report"]
    assert len(schema_tables(fake_teable)) == 15
    assert sorted(schema_tables(fake_teable)) == sorted(schema["tables"])
    assert sorted(report.created_tables) == sorted(schema["tables"])
    assert set(bootstrapped["table_ids"]) == set(schema["tables"])


def test_every_id_field_is_unique_and_not_null_on_the_server(fake_teable, bootstrapped, schema):
    for table, id_name in schema_mod.id_fields(schema).items():
        fields = {f["name"]: f for f in fake_teable.fields(table)}
        assert fields[id_name]["unique"] is True, table
        assert fields[id_name]["notNull"] is True, table
        assert fields[id_name]["isPrimary"] is True, table
        assert fields[id_name]["type"] == "singleLineText", table


def test_every_table_has_system_fields_and_choice_options(fake_teable, bootstrapped, schema):
    for table in schema["tables"]:
        by_name = {f["name"]: f for f in fake_teable.fields(table)}
        for system in schema["system_fields"]:
            assert by_name[system["name"]]["type"] == system["type"], (table, system["name"])
        for name, spec in schema["tables"][table]["fields"].items():
            if spec["type"] == "choice":
                got = [c["name"] for c in by_name[name]["options"]["choices"]]
                assert got == spec["choices"], (table, name)


def test_second_run_changes_nothing_and_reports_no_difference(
    fake_teable, client, base_id, schema, bootstrapped
):
    before = fake_teable.snapshot(skip_tables=(SCRATCH,))
    settings: dict = {}
    again = run_bootstrap(client, base_id=base_id, project_name="Test project", schema=schema, settings=settings)
    assert fake_teable.snapshot(skip_tables=(SCRATCH,)) == before
    assert not again.changed
    assert not again.has_differences
    assert again.created_tables == [] and again.created_fields == [] and again.created_settings == []
    assert settings["table_ids"] == bootstrapped["table_ids"]
    assert again.scratch_ok


def test_default_cai_dat_rows_written_once_and_never_overwritten(fake_teable, client, base_id, schema, bootstrapped):
    rows = {r["fields"]["khoa"]: r["fields"].get("gia_tri") for r in fake_teable.records("cai_dat")}
    expected = {r["khoa"] for r in schema["defaults"]["cai_dat"]}
    assert set(rows) == expected
    assert rows["ten_du_an"] == "Test project"
    assert (rows["so_uv_toi_thieu"], rows["so_uv_toi_da"]) == ("3", "5")
    assert rows["chot_cap_1"] == "Không" and rows["chot_cap_2"] == "Không"
    # a user changes a setting; a rerun must keep it
    table_id = bootstrapped["table_ids"]["cai_dat"]
    record = next(r for r in client.list_all_records(table_id) if r["fields"]["khoa"] == "so_uv_toi_da")
    client.update_record(table_id, record["id"], {"gia_tri": "7"})
    run_bootstrap(client, base_id=base_id, project_name="Other name", schema=schema, settings={})
    after = {r["fields"]["khoa"]: r["fields"].get("gia_tri") for r in fake_teable.records("cai_dat")}
    assert after["so_uv_toi_da"] == "7"
    assert after["ten_du_an"] == "Test project"
    assert len(fake_teable.records("cai_dat")) == len(expected)


def test_bootstrap_adds_new_rate_rows_to_an_old_base_and_changes_nothing_else(
    fake_teable, client, base_id, schema
):
    old_schema = copy.deepcopy(schema)  # what the previous version wrote
    old_schema["defaults"]["cai_dat"] = [r for r in old_schema["defaults"]["cai_dat"]
                                         if not r["khoa"].startswith("vnd_per_")] + [
        {"khoa": "ty_gia_VND", "gia_tri": "0.000001"}, {"khoa": "ty_gia_USD", "gia_tri": "0.025"},
        {"khoa": "ty_gia_EUR", "gia_tri": "0.027"}]
    first = run_bootstrap(client, base_id=base_id, project_name="Old", schema=old_schema, settings={})
    assert first.obsolete_settings == []  # the old schema did not know the old keys as obsolete
    before = {r["fields"]["khoa"]: dict(r["fields"]) for r in fake_teable.records("cai_dat")}
    snap_other = fake_teable.snapshot(skip_tables=(SCRATCH, "cai_dat"))
    report = run_bootstrap(client, base_id=base_id, project_name="New", schema=schema, settings={})
    after = {r["fields"]["khoa"]: dict(r["fields"]) for r in fake_teable.records("cai_dat")}
    assert set(report.created_settings) == {"vnd_per_usd", "vnd_per_eur"}
    assert after["vnd_per_usd"]["gia_tri"] == "25000" and after["vnd_per_eur"]["gia_tri"] == "27000"
    assert {k: v for k, v in after.items() if k in before} == before  # every old row untouched
    assert before["ty_gia_EUR"]["gia_tri"] == "0.027"  # not deleted, not converted
    assert fake_teable.snapshot(skip_tables=(SCRATCH, "cai_dat")) == snap_other
    assert report.obsolete_settings == ["ty_gia_VND", "ty_gia_USD", "ty_gia_EUR"]
    text = " ".join(report.lines())
    assert "OBSOLETE" in text and "ty_gia_EUR" in text
    again = run_bootstrap(client, base_id=base_id, project_name="New", schema=schema, settings={})
    assert again.created_settings == [] and again.obsolete_settings == report.obsolete_settings


def test_table_ids_are_saved_in_settings_and_file_without_token(client, base_id, schema, tmp_path: Path):
    settings: dict = {}
    path = tmp_path / "sub" / "settings.json"
    run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings=settings, settings_path=path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["base_id"] == base_id
    assert set(saved["table_ids"]) == set(schema["tables"])
    assert all(v.startswith("tbl") for v in saved["table_ids"].values())
    assert "tester" not in path.read_text(encoding="utf-8")  # the token used by the fixture client


def test_missing_field_is_added_on_rerun(fake_teable, client, base_id, schema, bootstrapped):
    fake_teable.drop_field("ung_vien", "ly_do")
    again = run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})
    assert again.created_fields == ["ung_vien.ly_do"]
    assert "ly_do" in {f["name"] for f in fake_teable.fields("ung_vien")}


def test_rerun_reports_but_does_not_fix_a_dropped_unique_flag(fake_teable, client, base_id, schema, bootstrapped):
    fake_teable.drop_unique("ung_vien", "ma_uv")
    again = run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})
    assert again.has_differences
    assert [str(m) for m in again.mismatches] == ["ung_vien.ma_uv: unique is False, schema says True"]
    still = {f["name"]: f for f in fake_teable.fields("ung_vien")}["ma_uv"]
    assert still["unique"] is False  # reported, not changed


def test_rerun_reports_a_wrong_field_type(fake_teable, client, base_id, schema, bootstrapped):
    with fake_teable._lock:
        fake_teable._field(fake_teable._table_by_name("moc"), "ten")["type"] = "longText"
    again = run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})
    assert [(m.table, m.field, m.what) for m in again.mismatches] == [("moc", "ten", "type")]


def test_bootstrap_creates_base_from_project_name_and_space(client, schema):
    settings: dict = {}
    report = run_bootstrap(client, project_name="New project", space_id="spc1", schema=schema, settings=settings)
    assert report.base_id.startswith("bse")
    assert settings["base_id"] == report.base_id


def test_bootstrap_needs_a_base_or_a_name_with_space(client, schema):
    with pytest.raises(BootstrapError, match="base id"):
        run_bootstrap(client, schema=schema, settings={})


# ---- scratch table: duplicate ID must be refused -------------------------------


def test_scratch_check_sees_the_second_record_refused(fake_teable, bootstrapped):
    assert bootstrapped["report"].scratch_ok
    records = fake_teable.records(SCRATCH)
    assert len(records) == 1  # the duplicate never landed
    assert records[0]["fields"]["ma"].startswith("SCRATCH-")
    assert bootstrapped["settings"]["scratch_table_id"] == fake_teable.table_id(SCRATCH)


def test_bootstrap_fails_clearly_when_server_does_not_enforce_unique(base_id, schema):
    with FakeTeable(enforce_unique=False) as lax:
        with TeableClient(lax.url, "tester", backoff=0) as client:
            with pytest.raises(BootstrapError, match="first-come ID rule would not hold"):
                run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})


def test_scratch_check_does_not_pass_on_a_server_error(client, base_id, schema, monkeypatch):
    run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})
    real_create = client.create_record
    calls = {"scratch": 0}

    def flaky(table_id, fields, **kwargs):
        if "ma" in fields:
            calls["scratch"] += 1
            if calls["scratch"] == 2:
                raise TeableError("boom", status=500, method="POST", path="/record")
        return real_create(table_id, fields, **kwargs)

    monkeypatch.setattr(client, "create_record", flaky)
    with pytest.raises(BootstrapError, match="boom"):
        run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})


def test_scratch_check_does_not_pass_on_another_client_error(client, base_id, schema, monkeypatch):
    """Only a unique violation proves the rule; a 404 or a not-null 400 must not count as refusal."""
    run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})
    real_create = client.create_record
    calls = {"scratch": 0}

    def wrong_refusal(table_id, fields, **kwargs):
        if "ma" in fields:
            calls["scratch"] += 1
            if calls["scratch"] == 2:
                raise TeableError("field is empty", status=400, method="POST", path="/record",
                                  code="validation_error", domain_code="validation.field.not_null")
        return real_create(table_id, fields, **kwargs)

    monkeypatch.setattr(client, "create_record", wrong_refusal)
    with pytest.raises(BootstrapError, match="field is empty"):
        run_bootstrap(client, base_id=base_id, project_name="P", schema=schema, settings={})


# ---- acceptance test 4: unique flag removed -> commit must be refused ----------


def test_unique_flags_check_passes_on_fresh_bootstrap(client, bootstrapped, schema):
    client.ensure_unique_flags(bootstrapped["table_ids"], schema_mod.id_fields(schema))
    assert client.missing_unique_flags(bootstrapped["table_ids"], schema_mod.id_fields(schema)) == []


def test_removed_unique_flag_is_detected_and_named(fake_teable, client, bootstrapped, schema):
    fake_teable.drop_unique("thong_so", "ma_ts")
    with pytest.raises(UniqueFlagError) as caught:
        client.ensure_unique_flags(bootstrapped["table_ids"], schema_mod.id_fields(schema))
    assert caught.value.fields == ["thong_so.ma_ts"]
    assert "thong_so.ma_ts" in str(caught.value)


def test_every_id_field_is_checked_not_just_the_first(fake_teable, client, bootstrapped, schema):
    for table, id_name in schema_mod.id_fields(schema).items():
        fake_teable.drop_unique(table, id_name)
        missing = client.missing_unique_flags(bootstrapped["table_ids"], schema_mod.id_fields(schema))
        assert missing == [f"{table}.{id_name}"]
        with fake_teable._lock:  # restore for the next table
            fake_teable._field(fake_teable._table_by_name(table), id_name)["unique"] = True


# ---- command line --------------------------------------------------------------


def test_cli_bootstrap_runs_end_to_end(fake_teable, tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("T3DESK_TEABLE_TOKEN", "cli-secret-token")
    out = tmp_path / "s.json"
    code = cli_main(["bootstrap", "--url", fake_teable.url, "--base-id", "bseCLI", "--project-name", "P",
                     "--settings-file", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "cli-secret-token" not in text and "cli-secret-token" not in out.read_text(encoding="utf-8")
    assert len(json.loads(out.read_text(encoding="utf-8"))["table_ids"]) == 15
    assert cli_main(["bootstrap", "--url", fake_teable.url, "--base-id", "bseCLI"]) == 0


def test_cli_reports_wrong_address_without_traceback(capsys, monkeypatch):
    monkeypatch.setenv("T3DESK_TEABLE_TOKEN", "x")
    code = cli_main(["bootstrap", "--url", "http://127.0.0.1:1", "--base-id", "b"])
    assert code == 2
    assert "Bootstrap failed" in capsys.readouterr().err


def test_main_without_ui_module_exits_cleanly(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "t3desk.server", None)  # import fails
    assert cli_main([]) == 2
    assert "not built yet" in capsys.readouterr().err
