"""Store (drafts, cache, settings, secrets), validation, and acceptance test 8 (offline)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from t3desk import schema as schema_mod
from t3desk import validation
from t3desk.commit import Committer, CommitDisabledError
from t3desk.store import Store, load_secret, save_secret

T0 = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


# ---- drafts and cache -------------------------------------------------------


def test_draft_roundtrip_and_survives_reopen(tmp_path: Path):
    path = tmp_path / "me.sqlite"
    with Store(path) as store:
        d = store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R1", "mo_ta": "Tiếng Việt ok"})
        store.update_draft(d.id, fields={"ma_yc": "R1", "mo_ta": "changed"})
    with Store(path) as again:
        [kept] = again.list_drafts()
        assert (kept.table, kept.op, kept.key) == ("yeu_cau", "create", "R1")
        assert kept.fields["mo_ta"] == "changed"
        again.remove_draft(kept.id)
        assert again.count_drafts() == 0


def test_update_draft_needs_record_id_and_create_needs_id(tmp_path: Path):
    with Store(tmp_path / "s.sqlite") as store:
        with pytest.raises(ValueError):
            store.add_draft("yeu_cau", "ma_yc", {"mo_ta": "x"})
        with pytest.raises(ValueError):
            store.add_draft("yeu_cau", "ma_yc", {"mo_ta": "x"}, op="update", key="R1")


def test_cache_has_fetch_age(tmp_path: Path):
    clock = Clock(T0)
    with Store(tmp_path / "s.sqlite", clock=clock) as store:
        assert store.cache_age("yeu_cau") is None
        store.replace_cache("yeu_cau", [{"id": "rec1", "fields": {"ma_yc": "R1"}}])
        clock.now = T0 + timedelta(minutes=90)
        assert store.cache_age("yeu_cau") == timedelta(minutes=90)
        assert store.cache_ids("yeu_cau", "ma_yc") == {"R1"}
        store.replace_cache("yeu_cau", [{"id": "rec2", "fields": {"ma_yc": "R2"}}])  # replaces, not appends
        assert store.cache_ids("yeu_cau", "ma_yc") == {"R2"}
        assert store.cache_age("yeu_cau") == timedelta(0)
        assert store.oldest_cache_age() == timedelta(0)


def test_settings_roundtrip_and_refuse_secrets(tmp_path: Path):
    with Store(tmp_path / "s.sqlite") as store:
        store.set_setting("role", "Kỹ sư")
        store.set_setting("table_ids", {"yeu_cau": "tbl1"})
        assert store.get_setting("role") == "Kỹ sư"
        assert store.get_setting("missing", 7) == 7
        for bad in ("teable_token", "API_SECRET", "password"):
            with pytest.raises(ValueError):
                store.set_setting(bad, "x")


# ---- secrets ----------------------------------------------------------------


class FakeKeyring:
    class backend:  # looks like a real backend to the helper
        pass

    def __init__(self):
        self.saved: dict[tuple[str, str], str] = {}

    def get_keyring(self):
        return self.backend()

    def set_password(self, service, name, value):
        self.saved[(service, name)] = value

    def get_password(self, service, name):
        return self.saved.get((service, name))


def test_secret_goes_to_keyring_when_available(tmp_path: Path):
    kr = FakeKeyring()
    assert save_secret("t3desk", "tok", "s3cr3t", fallback_dir=tmp_path, keyring_module=kr) == "keyring"
    assert load_secret("t3desk", "tok", fallback_dir=tmp_path, keyring_module=kr) == "s3cr3t"
    assert list(tmp_path.iterdir()) == []


def test_secret_falls_back_to_user_only_file(tmp_path: Path):
    assert save_secret("t3desk", "tok", "s3cr3t", fallback_dir=tmp_path / "cfg", keyring_module=None) == "file"
    assert load_secret("t3desk", "tok", fallback_dir=tmp_path / "cfg", keyring_module=None) == "s3cr3t"
    [path] = (tmp_path / "cfg").iterdir()
    if os.name != "nt":  # Windows has no POSIX mode bits; the file sits in the user's profile folder
        assert path.stat().st_mode & 0o077 == 0


def test_secret_falls_back_when_keyring_raises(tmp_path: Path):
    class Broken(FakeKeyring):
        def set_password(self, *args):
            raise RuntimeError("no dbus")

    assert save_secret("t3desk", "tok", "v", fallback_dir=tmp_path, keyring_module=Broken()) == "file"
    assert load_secret("t3desk", "tok", fallback_dir=tmp_path, keyring_module=Broken()) == "v"


def test_secret_never_lands_in_sqlite(tmp_path: Path):
    db = tmp_path / "s.sqlite"
    with Store(db) as store:
        store.set_setting("teable_url", "http://nas:3000")
        store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R1", "mo_ta": "x"})
        save_secret("t3desk", "tok", "TOKEN-VALUE-123", fallback_dir=tmp_path / "cfg", keyring_module=None)
    raw = db.read_bytes()
    assert b"TOKEN-VALUE-123" not in raw
    with sqlite3.connect(db) as con:
        dump = "\n".join(con.iterdump())
    assert "TOKEN-VALUE-123" not in dump


# ---- acceptance test 8 ------------------------------------------------------


def test_offline_start_shows_cache_with_age_keeps_drafts_and_disables_commit(
    bootstrapped, fake_teable, make_client, schema, tmp_path: Path
):
    path = tmp_path / "me.sqlite"
    clock = Clock(T0)
    fake_teable.seed("yeu_cau", {"ma_yc": "R1", "mo_ta": "cached", "muc": "Bắt buộc", "trang_thai": "Nháp"})
    store = Store(path, clock=clock)
    committer = Committer(make_client("me"), store, schema, bootstrapped["table_ids"])
    committer.refresh_cache()
    store.close()

    fake_teable.stop()  # the NAS is gone

    clock.now = T0 + timedelta(hours=3)
    store = Store(path, clock=clock)  # "restart" of the app
    committer = Committer(make_client("me", retries=0), store, schema, bootstrapped["table_ids"])
    cached = store.cache_records("yeu_cau")
    assert [r["fields"]["ma_yc"] for r in cached] == ["R1"]
    assert store.cache_age("yeu_cau") == timedelta(hours=3)

    ok, why = committer.can_commit()
    assert not ok and why

    store.add_draft("yeu_cau", "ma_yc", {"ma_yc": "R2", "mo_ta": "offline work", "muc": "Bắt buộc",
                                         "trang_thai": "Nháp"})
    with pytest.raises(CommitDisabledError):
        committer.commit()
    store.close()

    store = Store(path, clock=clock)  # restart again: the draft is still there
    assert [d.key for d in store.list_drafts()] == ["R2"]
    assert store.cache_ids("yeu_cau", "ma_yc") == {"R1"}
    store.close()


# ---- validation -------------------------------------------------------------

KNOWN = {"nut": {"N1"}, "ung_vien": {"UV-001"}, "thong_so": {"TS-001"}, "yeu_cau": {"R1"}}


def codes(table: str, fields: dict, schema: schema_mod.Schema, **kw) -> set[str]:
    known = kw.pop("known", KNOWN)
    return {i.code for i in validation.validate_record(schema, table, fields, known_ids=known, **kw)}


def test_valid_candidate_has_no_issues(schema):
    assert codes("ung_vien", {"ma_uv": "UV-007", "ma_nut": "N1", "model": "X", "trang_thai": "Ứng viên"}, schema) == set()


@pytest.mark.parametrize("bad_id", ["uv-1", "UV-7", "UV-007x", "", None])
def test_id_format_and_required(schema, bad_id):
    found = codes("ung_vien", {"ma_uv": bad_id, "ma_nut": "N1", "model": "X", "trang_thai": "Ứng viên"}, schema)
    assert found & {"id_format", "required"}


def test_required_fields_reported(schema):
    found = validation.validate_record(schema, "ung_vien", {"ma_uv": "UV-001"}, known_ids=KNOWN)
    assert {i.field for i in found if i.code == "required"} == {"ma_nut", "model", "trang_thai"}


def test_allowed_values_and_numbers(schema):
    base = {"ma_kt": "KT-A", "ten": "A", "trang_thai": "Chọn"}
    assert codes("kien_truc", {**base, "trang_thai": "Sai"}, schema) == {"not_allowed"}
    assert codes("kien_truc", {**base, "diem_ky_thuat": 6}, schema) == {"range"}
    assert codes("kien_truc", {**base, "diem_ky_thuat": 2.5}, schema) == {"type"}
    assert codes("kien_truc", {**base, "diem_ky_thuat": "3"}, schema) == {"type"}
    assert codes("kien_truc", {**base, "diem_ky_thuat": 3}, schema) == set()
    assert codes("moc", {"ma_moc": "G4a", "ten": "x", "ngay_co_so": "20/10/2026"}, schema) == {"type"}
    assert codes("moc", {"ma_moc": "G4a", "ten": "x", "ngay_co_so": "2026-10-20"}, schema) == set()
    assert codes("yeu_cau", {"ma_yc": "R2", "mo_ta": "x", "muc": "Bắt buộc", "trang_thai": "Nháp", "zzz": 1},
                 schema) == {"unknown_field"}


def test_reference_must_exist_in_cache_or_drafts(schema):
    row = {"ma_uv": "UV-002", "ma_nut": "N9", "model": "X", "trang_thai": "Ứng viên"}
    found = validation.validate_record(schema, "ung_vien", row, known_ids=KNOWN)
    assert [(i.field, i.code) for i in found] == [("ma_nut", "missing_ref")]
    assert "N9" in found[0].message
    assert codes("ung_vien", row, schema, known={**KNOWN, "nut": {"N1", "N9"}}) == set()


def test_multi_reference_and_ref_extra(schema):
    arch = {"ma_kt": "KT-A", "ten": "A", "trang_thai": "Chọn", "yc_then_chot": "R1;R2"}
    assert codes("kien_truc", arch, schema) == {"missing_ref"}
    spec = {"ma_ts": "TS-002", "ma_nut": "N1", "ma_yc_goc": "Dẫn xuất", "thong_so": "x", "kieu": "Số", "muc": "Bắt buộc"}
    assert codes("thong_so", spec, schema) == set()  # the literal is accepted without a lookup
    assert codes("thong_so", {**spec, "ma_yc_goc": "R7"}, schema) == {"missing_ref"}


def test_node_cannot_be_its_own_parent(schema):
    node = {"ma_nut": "N1.1", "ma_cha": "N1.1", "ten": "x", "loai": "Cụm"}
    assert codes("nut", node, schema, known={"nut": {"N1.1"}}) == {"self_ref"}


def test_update_checks_only_changed_fields_and_blocks_id_change(schema):
    assert codes("ung_vien", {"model": "New"}, schema, op="update", key="UV-001") == set()
    assert codes("ung_vien", {"model": ""}, schema, op="update", key="UV-001") == {"required"}
    assert codes("ung_vien", {"ma_uv": "UV-002"}, schema, op="update", key="UV-001") == {"id_immutable"}


def test_known_ids_from_store_unions_cache_and_own_create_drafts(schema, tmp_path: Path):
    with Store(tmp_path / "s.sqlite") as store:
        store.replace_cache("nut", [{"id": "r1", "fields": {"ma_nut": "N1"}}])
        store.add_draft("nut", "ma_nut", {"ma_nut": "N2", "ten": "x", "loai": "Cụm"})
        d = store.add_draft("ung_vien", "ma_uv", {"ma_uv": "UV-001", "ma_nut": "N2", "model": "m",
                                                  "trang_thai": "Ứng viên"})
        assert validation.known_ids_from(schema, store)["nut"] == {"N1", "N2"}
        assert validation.validate_store_draft(schema, store, d.id) == []
        bad = store.add_draft("ung_vien", "ma_uv", {"ma_uv": "UV-002", "ma_nut": "N3", "model": "m",
                                                    "trang_thai": "Ứng viên"})
        assert [i.code for i in validation.validate_store_draft(schema, store, bad.id)] == ["missing_ref"]
