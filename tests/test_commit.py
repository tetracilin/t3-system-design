"""Commit flow: acceptance tests 2, 3, 4, 5, 6, 7 of docs/REQUIREMENTS.md section 12, plus edges."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fake_teable import FakeTeable
from t3desk import schema as schema_mod
from t3desk.bootstrap import run_bootstrap
from t3desk.commit import (
    COMMITTED, CONFLICT, FAILED, SKIPPED, STALE, Committer, CommitDisabledError,
)
from t3desk.store import Store
from t3desk.teable_client import TeableClient, UniqueFlagError


@pytest.fixture
def user(bootstrapped: dict[str, Any], fake_teable: FakeTeable, make_client: Callable[..., TeableClient],
         schema: schema_mod.Schema, tmp_path: Path) -> Callable[[str], SimpleNamespace]:
    """user("A") -> a separate app instance: own token, own SQLite file, own Committer."""
    table_ids = bootstrapped["table_ids"]
    opened: list[Store] = []

    def factory(name: str) -> SimpleNamespace:
        store = Store(tmp_path / f"{name}.sqlite")
        opened.append(store)
        client = make_client(name)
        committer = Committer(client, store, schema, table_ids)

        def draft(table: str, **fields: Any):
            return store.add_draft(table, schema_mod.id_field(schema, table), fields)

        return SimpleNamespace(name=name, store=store, client=client, committer=committer, draft=draft)

    yield factory
    for store in opened:
        store.close()


def seed_node(fake: FakeTeable, code: str = "N1") -> None:
    fake.seed("nut", {"ma_nut": code, "ten": f"Node {code}", "loai": "Mua OEM"})


def seed_spec(fake: FakeTeable, code: str = "TS-001", node: str = "N1") -> None:
    fake.seed("thong_so", {"ma_ts": code, "ma_nut": node, "ma_yc_goc": "Dẫn xuất",
                           "thong_so": "Range", "kieu": "Số"})


def candidate(model: str, node: str = "N1", code: str = "UV-007") -> dict[str, Any]:
    return {"ma_uv": code, "ma_nut": node, "model": model, "trang_thai": "Ứng viên"}


def req(code: str, text: str = "text") -> dict[str, Any]:
    return {"ma_yc": code, "mo_ta": text, "muc": "Bắt buộc", "trang_thai": "Nháp"}


def record_by_id(fake: FakeTeable, table: str, id_field: str, code: str) -> list[dict[str, Any]]:
    return [r for r in fake.records(table) if r["fields"].get(id_field) == code]


# ---- acceptance test 2 ------------------------------------------------------


def test_duplicate_id_later_user_gets_new_id_and_references_follow(user, fake_teable):
    seed_node(fake_teable)
    seed_spec(fake_teable)
    a, b = user("A"), user("B")
    a.draft("ung_vien", **candidate("A-model"))
    b.draft("ung_vien", **candidate("B-model"))
    check = b.draft("doi_chieu", khoa="UV-007|TS-001", ma_uv="UV-007", ma_ts="TS-001", danh_gia_tay="Đạt")

    assert a.committer.commit().ok
    first = fake_teable.records("ung_vien")[0]

    report = b.committer.commit()
    by_table = {r.table: r for r in report.results}
    conflict = by_table["ung_vien"]
    assert conflict.status == CONFLICT
    assert conflict.conflict.id == "UV-007"
    assert conflict.conflict.taken_by == "A"
    assert conflict.conflict.taken_at == first["createdTime"]
    assert conflict.conflict.proposed_id == "UV-008"
    assert "UV-007" in conflict.message and "A" in conflict.message
    # The check depends on the conflicting candidate, so it must NOT be sent pointing at A's record.
    assert by_table["doi_chieu"].status == SKIPPED
    assert fake_teable.records("doi_chieu") == []

    rewritten = b.committer.accept_new_id(conflict.draft_id, "UV-008")
    assert rewritten == 1
    moved = b.store.get_draft(check.id)
    assert moved.fields["ma_uv"] == "UV-008"
    assert moved.fields["khoa"] == moved.key == "UV-008|TS-001"

    second = b.committer.commit()
    assert second.ok, second.lines()
    ung_vien = {r["fields"]["ma_uv"]: r for r in fake_teable.records("ung_vien")}
    assert set(ung_vien) == {"UV-007", "UV-008"}
    assert ung_vien["UV-007"] == first  # A's record is byte for byte unchanged
    assert ung_vien["UV-008"]["fields"]["model"] == "B-model"
    assert fake_teable.records("doi_chieu")[0]["fields"]["ma_uv"] == "UV-008"
    assert b.store.count_drafts() == 0


def test_conflict_handler_renames_and_continues_in_one_commit(user, fake_teable):
    seed_node(fake_teable)
    seed_spec(fake_teable)
    a, b = user("A"), user("B")
    a.draft("ung_vien", **candidate("A-model"))
    b.draft("ung_vien", **candidate("B-model"))
    b.draft("doi_chieu", khoa="UV-007|TS-001", ma_uv="UV-007", ma_ts="TS-001")
    a.committer.commit()

    asked: list[Any] = []

    def accept(info, draft):
        asked.append(info)
        return info.proposed_id

    report = b.committer.commit(on_conflict=accept)
    assert report.ok, report.lines()
    assert [i.id for i in asked] == ["UV-007"]
    assert {r["fields"]["ma_uv"] for r in fake_teable.records("ung_vien")} == {"UV-007", "UV-008"}
    assert fake_teable.records("doi_chieu")[0]["fields"]["khoa"] == "UV-008|TS-001"


def test_accept_new_id_rewrites_multi_value_and_rejects_bad_ids(user, fake_teable):
    b = user("B")
    r1 = b.draft("yeu_cau", **req("R1"))
    b.draft("yeu_cau", **req("R2"))
    arch = b.draft("kien_truc", ma_kt="KT-A", ten="A", yc_then_chot="R1;R2", trang_thai="Đề xuất")
    with pytest.raises(ValueError):
        b.committer.accept_new_id(r1.id, "R2")  # already one of my drafts
    with pytest.raises(ValueError):
        b.committer.accept_new_id(r1.id, "X9")  # wrong format
    assert b.committer.accept_new_id(r1.id, "R5") == 1
    assert b.store.get_draft(arch.id).fields["yc_then_chot"] == "R5;R2"
    assert b.store.get_draft(r1.id).key == "R5"


# ---- acceptance test 3 ------------------------------------------------------


def test_two_threads_commit_same_new_id_exactly_one_wins(user, fake_teable):
    fake_teable.set_delay(0.05, method="POST", path_contains="record")
    a, b = user("A"), user("B")
    a.draft("yeu_cau", **req("R1", "from A"))
    b.draft("yeu_cau", **req("R1", "from B"))
    barrier = threading.Barrier(2)
    reports: dict[str, Any] = {}

    def run(who) -> None:
        barrier.wait()
        reports[who.name] = who.committer.commit()

    threads = [threading.Thread(target=run, args=(w,)) for w in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)

    assert len(record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")) == 1
    statuses = sorted(r.results[0].status for r in reports.values())
    assert statuses == [COMMITTED, CONFLICT]
    winner = next(n for n, r in reports.items() if r.results[0].status == COMMITTED)
    loser = next(n for n, r in reports.items() if r.results[0].status == CONFLICT)
    assert record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]["mo_ta"] == f"from {winner}"
    conflict = reports[loser].results[0].conflict
    assert conflict.taken_by == winner and conflict.proposed_id == "R2"
    assert {"A": a, "B": b}[loser].store.count_drafts() == 1  # the loser keeps its draft


def test_read_back_earlier_record_wins_and_ours_is_withdrawn(schema, tmp_path):
    """Even if the server's unique rule fails to stop a duplicate, the earlier record keeps the ID."""
    with FakeTeable(enforce_unique=False) as server:
        client_a = TeableClient(server.url, "A", backoff=0.0)
        client_b = TeableClient(server.url, "B", backoff=0.0)
        try:
            settings: dict[str, Any] = {}
            run_bootstrap(client_a, base_id="bseX", project_name="P", schema=schema, settings=settings,
                          scratch_check=False)
            seed_node(server)
            first = server.seed("ung_vien", candidate("A-model"), user="A")
            store = Store(tmp_path / "b.sqlite")
            committer = Committer(client_b, store, schema, settings["table_ids"])
            # B's cache is refreshed inside commit(), so B's draft is built before it can see A.
            store.add_draft("ung_vien", "ma_uv", candidate("B-model"))
            # Hide A's record from the pre-check by committing at the moment B sends: unique is off,
            # so the server accepts the duplicate and only the read-back can resolve it.
            report = committer.commit()
            result = report.results[0]
            assert result.status == CONFLICT
            assert result.conflict.taken_by == "A"
            assert result.conflict.proposed_id == "UV-008"
            rows = record_by_id(server, "ung_vien", "ma_uv", "UV-007")
            assert len(rows) == 2
            original = next(r for r in rows if r["id"] == first["id"])
            assert original["fields"] == first["fields"]  # A's record untouched
            ours = next(r for r in rows if r["id"] != first["id"])
            assert ours["fields"]["trang_thai"] == "Loại"  # withdrawn by status, not deleted
            assert not any(e["method"] == "DELETE" for e in server.request_log)
            assert store.count_drafts() == 1
            store.close()
        finally:
            client_a.close()
            client_b.close()


# ---- acceptance test 4 (commit side) ---------------------------------------


def test_commit_refused_when_unique_flag_missing_names_the_field(user, fake_teable):
    a = user("A")
    a.draft("yeu_cau", **req("R1"))
    fake_teable.drop_unique("ung_vien", "ma_uv")
    posts_before = [e for e in fake_teable.request_log if e["method"] == "POST" and "record" in e["path"]]
    with pytest.raises(UniqueFlagError) as caught:
        a.committer.commit()
    assert "ung_vien.ma_uv" in str(caught.value)
    posts_after = [e for e in fake_teable.request_log if e["method"] == "POST" and "record" in e["path"]]
    assert len(posts_after) == len(posts_before)
    assert a.store.count_drafts() == 1
    assert fake_teable.records("yeu_cau") == []


# ---- acceptance test 5 ------------------------------------------------------


def _start_edit(who, fake_teable, changes: dict[str, Any]):
    who.committer.refresh_cache()
    rec = who.store.cache_records("yeu_cau")[0]
    return who.store.add_draft(
        "yeu_cau", "ma_yc", changes, op="update", record_id=rec["id"], key=rec["fields"]["ma_yc"],
        base_modified=rec["lastModifiedTime"], base_fields=rec["fields"],
    )


def test_stale_edit_shows_both_versions_and_user_chooses_per_field(user, fake_teable):
    original = fake_teable.seed("yeu_cau", {**req("R1", "original"), "muc": "Mong muốn"})
    a, b = user("A"), user("B")
    draft = _start_edit(a, fake_teable, {"mo_ta": "A text", "uu_tien": "H"})
    b.client.update_record(fake_teable.table_id("yeu_cau"), original["id"],
                           {"mo_ta": "B text", "muc": "Bắt buộc"})

    report = a.committer.commit()
    result = report.results[0]
    assert result.status == STALE
    info = result.stale
    rows = {f.field: f for f in info.fields}
    assert rows["mo_ta"].mine == "A text" and rows["mo_ta"].theirs == "B text" and rows["mo_ta"].base == "original"
    assert rows["mo_ta"].theirs_changed is True
    assert rows["uu_tien"].theirs_changed is False
    assert info.modified_by == "B"
    assert a.store.count_drafts() == 1  # still a draft
    assert record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]["mo_ta"] == "B text"  # nothing sent

    remaining = a.committer.resolve_stale(draft.id, {"mo_ta": "theirs"})
    assert remaining.fields == {"uu_tien": "H"}
    assert a.committer.commit().ok
    final = record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]
    assert (final["mo_ta"], final["uu_tien"], final["muc"]) == ("B text", "H", "Bắt buộc")


def test_stale_edit_choose_mine_through_handler(user, fake_teable):
    original = fake_teable.seed("yeu_cau", req("R1", "original"))
    a, b = user("A"), user("B")
    _start_edit(a, fake_teable, {"mo_ta": "A text"})
    b.client.update_record(fake_teable.table_id("yeu_cau"), original["id"], {"mo_ta": "B text"})
    seen = []
    report = a.committer.commit(on_stale=lambda info: seen.append(info) or {"mo_ta": "mine"})
    assert report.ok and len(seen) == 1
    assert record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]["mo_ta"] == "A text"


def test_unchanged_record_updates_without_stale_prompt(user, fake_teable):
    fake_teable.seed("yeu_cau", req("R1", "original"))
    a = user("A")
    _start_edit(a, fake_teable, {"mo_ta": "new"})
    assert a.committer.commit().ok
    assert record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]["mo_ta"] == "new"


def test_id_cannot_be_edited_after_commit(user, fake_teable):
    fake_teable.seed("yeu_cau", req("R1"))
    a = user("A")
    _start_edit(a, fake_teable, {"ma_yc": "R9"})
    result = a.committer.commit().results[0]
    assert result.status == FAILED and "cannot be changed" in result.message
    assert [r["fields"]["ma_yc"] for r in fake_teable.records("yeu_cau")] == ["R1"]


# ---- acceptance test 6 ------------------------------------------------------


def test_drafts_commit_in_dependency_order_node_candidate_check(user, fake_teable):
    a = user("A")
    # Entered in the worst order: check, candidate, specification, node.
    a.draft("doi_chieu", khoa="UV-001|TS-001", ma_uv="UV-001", ma_ts="TS-001", danh_gia_tay="Đạt")
    a.draft("ung_vien", **candidate("M1", code="UV-001"))
    a.draft("thong_so", ma_ts="TS-001", ma_nut="N1", ma_yc_goc="Dẫn xuất", thong_so="Range", kieu="Số", muc="Bắt buộc")
    a.draft("nut", ma_nut="N1", ten="Node", loai="Mua OEM")

    report = a.committer.commit()
    assert report.ok, report.lines()
    names = {fake_teable.table_id(t): t for t in ("nut", "ung_vien", "thong_so", "doi_chieu")}
    sent = [names[e["path"].split("/")[3]] for e in fake_teable.request_log
            if e["method"] == "POST" and e["path"].endswith("/record") and e["path"].split("/")[3] in names]
    assert sent.index("nut") < sent.index("ung_vien") < sent.index("doi_chieu")
    assert sent.index("nut") < sent.index("thong_so") < sent.index("doi_chieu")
    assert sent[0] == "nut" and sent[-1] == "doi_chieu"


def test_children_after_parents_and_one_create_per_request(user, fake_teable):
    a = user("A")
    a.draft("nut", ma_nut="N1.1", ma_cha="N1", ten="Child", loai="Mua OEM")
    a.draft("nut", ma_nut="N1", ma_cha="N0", ten="Mid", loai="Cụm")
    a.draft("nut", ma_nut="N0", ten="Root", loai="Hệ thống")
    assert a.committer.commit().ok
    assert [r["fields"]["ma_nut"] for r in fake_teable.records("nut")] == ["N0", "N1", "N1.1"]
    # Every create request carried exactly one record (no batch create).
    nut_posts = [e for e in fake_teable.request_log if e["method"] == "POST"
                 and e["path"] == f"/api/table/{fake_teable.table_id('nut')}/record"]
    assert len(nut_posts) == 3


def test_reference_loop_does_not_hang(user):
    a = user("A")
    a.draft("nut", ma_nut="N1", ma_cha="N1.1", ten="x", loai="Cụm")
    a.draft("nut", ma_nut="N1.1", ma_cha="N1", ten="y", loai="Cụm")
    ordered = a.committer.order_drafts(a.store.list_drafts())
    assert [d.key for d in ordered] == ["N1", "N1.1"]  # oldest first


# ---- acceptance test 7 ------------------------------------------------------


def test_one_conflict_does_not_stop_other_drafts(user, fake_teable):
    fake_teable.seed("yeu_cau", req("R1", "someone else"), user="Z")
    a = user("A")
    a.draft("yeu_cau", **req("R1", "mine"))
    a.draft("yeu_cau", **req("R2"))
    a.draft("yeu_cau", **req("R3"))
    report = a.committer.commit()
    assert [r.status for r in report.results] == [CONFLICT, COMMITTED, COMMITTED]
    assert {r["fields"]["ma_yc"] for r in fake_teable.records("yeu_cau")} == {"R1", "R2", "R3"}
    assert record_by_id(fake_teable, "yeu_cau", "ma_yc", "R1")[0]["fields"]["mo_ta"] == "someone else"
    assert [d.key for d in a.store.list_drafts()] == ["R1"]  # only the conflict stays a draft
    assert report.results[0].conflict.taken_by == "Z"
    assert report.results[0].conflict.proposed_id == "R4"


def test_failed_draft_with_server_message_does_not_stop_others(user, fake_teable):
    a = user("A")
    a.draft("yeu_cau", **req("R1"))
    a.draft("yeu_cau", **req("R2"))
    fake_teable.fail_next(400, "boom from server", method="POST", path_contains="/record")
    report = a.committer.commit()
    assert report.results[0].status == FAILED and "boom from server" in report.results[0].message
    assert report.results[1].status == COMMITTED
    assert a.store.count_drafts() == 1


def test_invalid_draft_is_not_sent_and_dependents_wait(user, fake_teable):
    a = user("A")
    a.draft("ung_vien", ma_uv="UV-001", ma_nut="N404", model="M", trang_thai="Ứng viên")  # node missing
    a.draft("doi_chieu", khoa="UV-001|TS-001", ma_uv="UV-001", ma_ts="TS-001")
    report = a.committer.commit()
    assert [r.status for r in report.results] == [FAILED, SKIPPED]
    assert "N404" in report.results[0].message
    assert fake_teable.records("ung_vien") == []


def test_nothing_is_ever_deleted(user, fake_teable):
    fake_teable.seed("yeu_cau", req("R1"))
    a = user("A")
    a.draft("yeu_cau", **req("R1", "dup"))
    a.draft("yeu_cau", **req("R2"))
    a.committer.commit()
    assert not any(e["method"] == "DELETE" for e in fake_teable.request_log)


def test_cache_is_refreshed_before_sending(user, fake_teable):
    seed_node(fake_teable)  # the draft's node exists only in Teable, never fetched before commit
    a = user("A")
    a.draft("ung_vien", **candidate("M1", code="UV-001"))
    assert a.store.cache_records("nut") == []
    report = a.committer.commit()
    assert report.ok, report.lines()
    assert a.store.cache_age("nut") is not None


def test_commit_disabled_when_server_stopped(user, fake_teable):
    a = user("A")
    a.committer.client = a.client = a.committer.client.__class__(fake_teable.url, "A", retries=0, timeout=5)
    a.draft("yeu_cau", **req("R1"))
    fake_teable.stop()
    ok, why = a.committer.can_commit()
    assert not ok and "not reachable" in why
    with pytest.raises(CommitDisabledError):
        a.committer.commit()
    assert a.store.count_drafts() == 1
