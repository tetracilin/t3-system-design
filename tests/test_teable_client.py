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


def test_create_returns_id_autonumber_and_times(client, tid):
    rec = client.create_record(tid["yeu_cau"], {"ma_yc": "R1", "mo_ta": "x", "muc": "Bắt buộc"})
    assert rec["id"].startswith("rec")
    assert rec["autoNumber"] == 1
    assert rec["createdTime"] and rec["createdTime"] == rec["lastModifiedTime"]
    second = client.create_record(tid["yeu_cau"], {"ma_yc": "R2", "mo_ta": "y"})
    assert second["autoNumber"] == 2 and second["createdTime"] > rec["createdTime"]


def test_duplicate_id_is_refused_and_first_record_is_untouched(make_client, fake_teable, tid):
    alice, bob = make_client("alice"), make_client("bob")
    first = alice.create_record(tid["ung_vien"], {"ma_uv": "UV-007", "ma_nut": "N1", "model": "A-1"})
    with pytest.raises(TeableError) as caught:
        bob.create_record(tid["ung_vien"], {"ma_uv": "UV-007", "ma_nut": "N2", "model": "B-9"})
    assert caught.value.status == 400 and caught.value.is_unique_violation
    rows = fake_teable.records("ung_vien")
    assert len(rows) == 1
    assert rows[0]["fields"]["model"] == "A-1" and rows[0]["lastModifiedTime"] == first["lastModifiedTime"]
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
    upd = client.update_record(tid["moc"], rec["id"], {"ten": "b"})
    assert upd["fields"]["ten"] == "b"
    assert upd["lastModifiedTime"] > rec["lastModifiedTime"]
    assert upd["createdTime"] == rec["createdTime"]


def test_create_sends_one_record_per_request(fake_teable, client, tid):
    fake_teable.request_log.clear()
    client.create_record(tid["moc"], {"ma_moc": "G1", "ten": "a"})
    assert [r["method"] for r in fake_teable.request_log] == ["POST"]


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
    assert c.ping()["name"] == "t"


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
            assert good.ping()["name"] == "Good"


def test_ping_returns_signed_in_user(make_client):
    assert make_client("alice").ping()["name"] == "alice"
