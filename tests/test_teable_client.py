"""teable_client.py against the fake server: paging, unique rule, retries, no delete."""

from __future__ import annotations

import inspect
import threading

import pytest

from fake_teable import FakeTeable
from t3desk import teable_client
from t3desk.teable_client import TeableClient, TeableConnectionError, TeableError, record_author


@pytest.fixture
def tid(bootstrapped) -> dict[str, str]:
    return bootstrapped["table_ids"]


def gets(fake, suffix="/record"):
    return [r for r in fake.request_log if r["method"] == "GET" and r["path"].endswith(suffix)]


# ---- paging -------------------------------------------------------------------


def test_list_all_pages_with_take_1000(fake_teable, client, tid):
    for n in range(2500):
        fake_teable.seed("moc", {"ma_moc": f"G{n}", "ten": f"m{n}"})
    fake_teable.request_log.clear()
    seen: list[int] = []
    records = client.list_all_records(tid["moc"], progress=seen.append)
    assert len(records) == 2500
    assert len({r["fields"]["ma_moc"] for r in records}) == 2500
    pages = [(r["query"]["take"], r["query"]["skip"]) for r in gets(fake_teable)]
    assert pages == [(["1000"], ["0"]), (["1000"], ["1000"]), (["1000"], ["2000"])]
    assert seen == [1000, 2000, 2500]


def test_exact_multiple_of_page_size_needs_one_empty_final_page(fake_teable, client, tid):
    for n in range(4):
        fake_teable.seed("moc", {"ma_moc": f"G{n}", "ten": "m"})
    assert len(client.list_all_records(tid["moc"], page_size=2)) == 4


def test_take_over_1000_is_refused_before_any_request(fake_teable, client, tid):
    fake_teable.request_log.clear()
    for bad in (1001, 0, -1):
        with pytest.raises(ValueError):
            client.list_records(tid["moc"], take=bad)
    assert fake_teable.request_log == []


def test_server_also_rejects_take_over_1000(fake_teable, client, tid):
    with pytest.raises(TeableError) as caught:
        client._request("GET", f"/api/table/{tid['moc']}/record", params={"take": 1001})
    assert caught.value.status == 400


def test_projection_and_filter(fake_teable, client, tid):
    fake_teable.seed("moc", {"ma_moc": "G1", "ten": "one"})
    fake_teable.seed("moc", {"ma_moc": "G2", "ten": "two"})
    found = client.find_by_field(tid["moc"], "ma_moc", "G2")
    assert [r["fields"]["ten"] for r in found] == ["two"]
    only = client.list_records(tid["moc"], projection=["ten"])
    assert all(set(r["fields"]) == {"ten"} for r in only)


# ---- records and the first-come rule -------------------------------------------


def test_create_answer_has_only_id_and_fields_and_get_has_the_times(client, tid):
    """Real Teable: the create answer carries no autoNumber or times; get and list do."""
    rec = client.create_record(tid["yeu_cau"], {"ma_yc": "R1", "mo_ta": "x", "muc": "Bắt buộc"})
    assert rec["id"].startswith("rec")
    assert set(rec) == {"id", "fields"} and rec["fields"] == {"ma_yc": "R1", "mo_ta": "x", "muc": "Bắt buộc"}
    got = client.get_record(tid["yeu_cau"], rec["id"])
    assert got["autoNumber"] == 1
    assert got["createdTime"] and got["createdTime"] == got["lastModifiedTime"]
    assert got["fields"]["created_by"]["title"]
    second = client.create_record(tid["yeu_cau"], {"ma_yc": "R2", "mo_ta": "y"})
    got2 = client.get_record(tid["yeu_cau"], second["id"])
    assert got2["autoNumber"] == 2 and got2["createdTime"] > got["createdTime"]


def test_unique_violation_has_the_real_message_and_codes(make_client, tid):
    c = make_client("alice")
    c.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    with pytest.raises(TeableError) as caught:
        c.create_record(tid["moc"], {"ma_moc": "G1", "ten": "b"})
    exc = caught.value
    assert exc.status == 400 and exc.code == "validation_error"
    assert exc.domain_code == "validation.field.unique"
    assert "must have a unique value" in exc.message and exc.is_unique_violation


def test_unique_violation_needs_the_unique_domain_code_when_present():
    other = TeableError("must have a unique value", status=400, domain_code="validation.field.not_null")
    assert not other.is_unique_violation
    assert TeableError("x", status=400, domain_code="validation.field.unique").is_unique_violation


def test_date_comes_back_as_plain_date(client, tid):
    rec = client.create_record(tid["ung_vien"], {"ma_uv": "UV-1", "ma_nut": "N1", "ngay_kiem_tra": "2026-10-05"})
    assert rec["fields"]["ngay_kiem_tra"] == "2026-10-05"
    assert client.get_record(tid["ung_vien"], rec["id"])["fields"]["ngay_kiem_tra"] == "2026-10-05"
    listed = client.list_all_records(tid["ung_vien"])
    assert listed[0]["fields"]["ngay_kiem_tra"] == "2026-10-05"
    assert listed[0]["fields"]["created_time"].endswith("Z")  # system times are left alone


def test_update_answer_has_fields_only_and_get_has_the_new_time(client, tid):
    rec = client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    before = client.get_record(tid["moc"], rec["id"])
    upd = client.update_record(tid["moc"], rec["id"], {"ten": None})
    assert set(upd) == {"id", "fields"} and "ten" not in upd["fields"]  # None clears the field
    assert client.get_record(tid["moc"], rec["id"])["lastModifiedTime"] > before["lastModifiedTime"]


def test_unknown_field_is_404_and_computed_field_is_ignored(client, tid):
    with pytest.raises(TeableError) as caught:
        client.create_record(tid["moc"], {"ma_moc": "G9", "nope": "x"})
    assert caught.value.status == 404 and "nope" in caught.value.message
    rec = client.create_record(tid["moc"], {"ma_moc": "G8", "created_time": "2020-01-01T00:00:00.000Z"})
    assert client.get_record(tid["moc"], rec["id"])["createdTime"] > "2026"


def test_create_field_with_existing_name_is_renamed_not_refused(client, tid):
    made = client.create_field(tid["moc"], {"name": "ten", "type": "singleLineText"})
    assert made["name"] == "ten 2"


def test_notnull_field_cannot_be_added_to_a_table_with_rows(client, tid):
    client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    with pytest.raises(TeableError) as caught:
        client.create_field(tid["moc"], {"name": "extra", "type": "singleLineText", "notNull": True})
    assert caught.value.status == 400 and caught.value.domain_code == "validation.field.required_existing_values"


def test_table_created_without_records_key_gets_blank_starter_rows(client):
    made = client._request("POST", "/api/base/bseX/table",
                           json_body={"name": "starter", "fields": [{"name": "a", "type": "singleLineText"}]})
    assert len(client.list_records(made["id"])) == 3  # why create_table sends records: []
    empty = client.create_table("bseX", "empty", [{"name": "a", "type": "singleLineText"}])
    assert client.list_records(empty["id"]) == []


def test_duplicate_id_is_refused_and_first_record_is_untouched(make_client, fake_teable, tid):
    alice, bob = make_client("alice"), make_client("bob")
    first = alice.create_record(tid["ung_vien"], {"ma_uv": "UV-007", "ma_nut": "N1", "model": "A-1"})
    with pytest.raises(TeableError) as caught:
        bob.create_record(tid["ung_vien"], {"ma_uv": "UV-007", "ma_nut": "N2", "model": "B-9"})
    assert caught.value.status == 400 and caught.value.is_unique_violation
    rows = fake_teable.records("ung_vien")
    assert len(rows) == 1
    assert rows[0]["fields"]["model"] == "A-1"
    assert rows[0]["lastModifiedTime"] == client_get(alice, tid, first)["lastModifiedTime"]
    assert record_author(client_get(alice, tid, first)) == "alice"


def client_get(client, tid, record):
    return client.get_record(tid["ung_vien"], record["id"])


def test_unique_violation_on_update_too(client, tid):
    client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    other = client.create_record(tid["moc"], {"ma_moc": "G2", "ten": "b"})
    with pytest.raises(TeableError) as caught:
        client.update_record(tid["moc"], other["id"], {"ma_moc": "G1"})
    assert caught.value.is_unique_violation


def test_other_client_errors_are_not_unique_violations(client, tid):
    with pytest.raises(TeableError) as caught:
        client.create_record(tid["moc"], {"ten": "no id"})  # notNull
    assert caught.value.status == 400 and not caught.value.is_unique_violation
    with pytest.raises(TeableError) as caught:
        client.create_record(tid["yeu_cau"], {"ma_yc": "R9", "muc": "Không có"})  # bad choice
    assert not caught.value.is_unique_violation


def test_two_threads_same_id_exactly_one_wins(make_client, fake_teable, tid):
    fake_teable.set_delay(0.05, method="POST", path_contains="/record")
    outcomes: list[object] = []
    barrier = threading.Barrier(2)

    def worker(user: str) -> None:
        c = make_client(user)
        barrier.wait()
        try:
            outcomes.append(c.create_record(tid["ung_vien"], {"ma_uv": "UV-100", "ma_nut": "N1", "model": user}))
        except TeableError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=worker, args=(u,)) for u in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fake_teable.records("ung_vien")) == 1
    assert sum(isinstance(o, TeableError) for o in outcomes) == 1
    assert next(o for o in outcomes if isinstance(o, TeableError)).is_unique_violation


def test_update_changes_last_modified_and_keeps_created(client, tid):
    rec = client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    first = client.get_record(tid["moc"], rec["id"])
    upd = client.update_record(tid["moc"], rec["id"], {"ten": "b"})
    assert upd["fields"]["ten"] == "b"
    after = client.get_record(tid["moc"], rec["id"])
    assert after["lastModifiedTime"] > first["lastModifiedTime"]
    assert after["createdTime"] == first["createdTime"]


def test_create_sends_one_record_per_request(fake_teable, client, tid):
    fake_teable.request_log.clear()
    client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    # one POST; the only other call is the once-per-table field lookup that finds the date fields
    assert [r["method"] for r in fake_teable.request_log] == ["POST", "GET"]
    assert fake_teable.request_log[1]["path"].endswith("/field")


# ---- no delete anywhere --------------------------------------------------------


def test_client_has_no_delete_call():
    source = inspect.getsource(teable_client)
    assert '"DELETE"' not in source and "'DELETE'" not in source
    assert not [n for n in dir(TeableClient) if "delete" in n.lower() or "remove" in n.lower()]


def test_delete_route_does_not_exist_on_fake(fake_teable, client, tid):
    rec = client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    with pytest.raises(TeableError) as caught:
        client._request("DELETE", f"/api/table/{tid['moc']}/record/{rec['id']}")
    assert caught.value.status == 405
    assert len(fake_teable.records("moc")) == 1


# ---- retries, timeouts, errors -------------------------------------------------


def test_get_is_retried_after_503(fake_teable, client, tid):
    fake_teable.request_log.clear()
    fake_teable.fail_next(503, "busy", method="GET", path_contains="/record", count=2)
    assert client.list_records(tid["moc"]) == []
    assert len(gets(fake_teable)) == 3


def test_get_gives_up_after_retries(fake_teable, make_client, tid):
    c = make_client("t", retries=1)
    fake_teable.fail_next(503, "busy", method="GET", path_contains="/record", count=5)
    with pytest.raises(TeableError) as caught:
        c.list_records(tid["moc"])
    assert caught.value.status == 503 and "busy" in str(caught.value)


def test_create_is_never_retried_after_a_server_error(fake_teable, client, tid):
    fake_teable.request_log.clear()
    fake_teable.fail_next(503, "busy", method="POST", path_contains="/record", count=1)
    with pytest.raises(TeableError):
        client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    assert len([r for r in fake_teable.request_log if r["method"] == "POST"]) == 1
    assert fake_teable.records("moc") == []


def test_read_timeout_on_create_is_not_retried(fake_teable, make_client, tid):
    c = make_client("t", timeout=0.2)
    fake_teable.request_log.clear()
    fake_teable.set_delay(0.6, method="POST", path_contains="/record", count=1)
    with pytest.raises(TeableConnectionError):
        c.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    assert len([r for r in fake_teable.request_log if r["method"] == "POST" and r["path"].endswith("/record")]) == 1


def test_server_down_raises_connection_error_with_clear_text(fake_teable, make_client):
    c = make_client("t", retries=1)
    fake_teable.stop()
    with pytest.raises(TeableConnectionError) as caught:
        c.ping()
    assert caught.value.status is None and "cannot reach Teable" in str(caught.value)
    fake_teable.start()  # same port, state kept
    assert c.ping()["user"]["name"] == "t"


def test_missing_token_is_a_401_and_token_never_appears_in_errors_or_repr(fake_teable, make_client):
    secret = "tok-SECRET-123"
    c = make_client(secret)
    assert secret not in repr(c)
    with pytest.raises(TeableError) as caught:
        c._request("GET", "/api/table/tblNOPE/field")
    assert caught.value.status == 404 and secret not in str(caught.value)


def test_rejected_token_gives_401(tid_unused=None):
    with FakeTeable(strict_auth=True, users={"good": "Good"}) as strict:
        with TeableClient(strict.url, "bad-token", backoff=0) as bad:
            with pytest.raises(TeableError) as caught:
                bad.ping()
            assert caught.value.status == 401 and "bad-token" not in str(caught.value)
        with TeableClient(strict.url, "good", backoff=0) as good:
            assert good.ping()["user"]["name"] == "Good"


def test_ping_returns_signed_in_user_and_spaces(make_client, fake_teable):
    info = make_client("alice").ping()
    assert info["user"]["name"] == "alice" and info["spaces"][0]["name"] == "T3"
    assert [r["path"] for r in fake_teable.request_log][-2:] == ["/api/space", "/api/auth/user"]


def test_ping_works_when_the_token_may_not_read_the_user(make_client, fake_teable):
    """A scoped token gets 403 on the user endpoint; /api/space still proves the token."""
    fake_teable.fail_next(403, "Forbidden resource", path_contains="/api/auth/user")
    info = make_client("alice").ping()
    assert info["user"] is None and info["spaces"]


def test_ping_refuses_an_anonymous_identity():
    with FakeTeable(users={"anon": "anonymous"}) as anon:
        with TeableClient(anon.url, "anon", backoff=0) as c:
            with pytest.raises(TeableError) as caught:
                c.ping()
            assert caught.value.status == 401 and "anonymous" in caught.value.message
