"""Task outbox: publishes open work as ``cong_viec`` rows that Paperclip TODO AI can sync (9.5).

The table is the contract. This plugin only creates and updates local drafts through the api;
the user's Commit sends them. Rules it keeps:

* ``ma_cv`` is built from source and subject, so two apps make the same row and Teable's unique
  flag stops duplicates. A unique conflict means "already exists": the draft is dropped.
* A row is updated only when title, description, owner, due date or status really changed.
* A task whose condition no longer holds is set to Xong, never removed.
* ``ma_ngoai`` and ``dong_bo_luc`` belong to Paperclip and are never written (the api refuses too).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from t3desk import rules

TABLE = "cong_viec"
SOURCES = ("buoc", "cho_nhan", "sai_lech", "rfq", "canh_bao")
COMPARED = ("tieu_de", "mo_ta", "nguoi_nhan", "han", "trang_thai")
OPEN, DONE = "Mở", "Xong"  # cong_viec.trang_thai values (schema choices)
RFQ_SENT = "Đã gửi"  # rfq.trang_thai value: sent, waiting for a reply
TASK_ROWS = rules.ACTIONABLE_ROWS | {9}  # next-action rows where the owner has work to do
PUSH_PATH = "/api/tasks"  # UNVERIFIED: no Paperclip TODO AI API reference exists
MAX_WARNING_LINES = 30

LABELS: dict[str, str] = yaml.safe_load(Path(__file__).with_name("labels.yaml").read_text(encoding="utf-8"))


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(field: str, value: Any) -> str:
    text = _s(value)
    return text[:10] if field == "han" else text


def make_key(source: str, subject: str) -> str:
    return f"CV|{source}|{subject}"


def _row(source: str, subject: str, title: str, desc: str, node: str, owner: str, due: str,
         today: str) -> dict[str, Any]:
    row = {"ma_cv": make_key(source, subject), "nguon": source, "tieu_de": title, "mo_ta": desc,
           "ma_nut": node, "nguoi_nhan": owner, "han": due, "trang_thai": OPEN, "cap_nhat_luc": today}
    return {k: v for k, v in row.items() if v != ""}


def desired_tasks(a: rules.Analysis, today: str) -> dict[str, dict[str, Any]]:
    """Every task that should be open now, keyed by ma_cv. Output depends only on the data."""
    out: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        out[row["ma_cv"]] = row

    for node in a.leaves:
        action = a.next_action(node)
        if action.row not in TASK_ROWS:
            continue
        name = _s(a.nodes[node].get("ten"))
        add(_row("buoc", node, LABELS["buoc_title"].format(node=node, action=action.text),
                 LABELS["buoc_desc"].format(node=node, name=name, action=action.text),
                 node, a.owner_of(node) or "", "", today))
    for uv in a.sourcing_queue():
        cand = a.cands[uv]
        node = _s(cand.get("ma_nut"))
        action = rules.TEXTS["next_wait_sourcing"]
        add(_row("cho_nhan", uv, LABELS["cho_nhan_title"].format(uv=uv, action=action),
                 LABELS["cho_nhan_desc"].format(uv=uv, hang=_s(cand.get("hang")), model=_s(cand.get("model")),
                                                node=node),
                 node, "", "", today))
    for card in a.t["sai_lech"]:
        if _s(card.get("trang_thai")) == rules.V.CHANGE_OPEN:
            code = _s(card.get("ma_sl"))
            add(_row("sai_lech", code, LABELS["sai_lech_title"].format(ma_sl=code, text=_s(card.get("mo_ta"))[:100]),
                     _s(card.get("mo_ta")), _s(card.get("ma_nut")), _s(card.get("nguoi_nhan")),
                     _s(card.get("han"))[:10], today))
    for req in a.t["rfq"]:
        due = _s(req.get("han_tra_loi"))[:10]
        if _s(req.get("trang_thai")) == RFQ_SENT and due and due < today:
            code = _s(req.get("ma_rfq"))
            fields = {"ma_rfq": code, "han": due, "loai": _s(req.get("loai")),
                      "vendor": _s(req.get("nha_cung_cap"))}
            add(_row("rfq", code, LABELS["rfq_title"].format(**fields), LABELS["rfq_desc"].format(**fields),
                     _s(req.get("ds_ma_nut")).split(";")[0].strip(), "", due, today))
    by_owner: dict[str, list[str]] = defaultdict(list)
    for warning in a.warnings():
        if warning.owner:
            by_owner[warning.owner].append(f"{warning.table} {warning.key}: {warning.text}")
    for owner, lines in sorted(by_owner.items()):
        lines = sorted(set(lines))
        shown = lines[:MAX_WARNING_LINES]
        add(_row("canh_bao", owner, LABELS["canh_bao_title"].format(owner=owner, count=len(lines)),
                 LABELS["canh_bao_desc"].format(lines="\n".join(shown)), "", owner, "", today))
    return out


def _diff(current: dict[str, Any], wanted: dict[str, Any]) -> dict[str, Any]:
    return {f: wanted.get(f, "") for f in COMPARED if _norm(f, current.get(f)) != _norm(f, wanted.get(f))}


def rebuild(api: Any, skip_keys: frozenset[str] = frozenset()) -> dict[str, int]:
    """Draft the creates and updates that bring cong_viec in line with the rules."""
    today = api.today().isoformat()
    wanted = desired_tasks(api.rules(), today)
    existing = {_s(r.get("ma_cv")): r for r in api.read(TABLE)}
    drafts = {d.key: d for d in api.list_drafts(TABLE)}
    counts = {"created": 0, "updated": 0, "closed": 0}
    pushed: list[dict[str, Any]] = []

    for key, row in wanted.items():
        if key in skip_keys:
            continue
        if key in existing:
            effective = {**existing[key], **(drafts[key].fields if key in drafts else {})}
            changes = _diff(effective, row)
            if changes and api.draft_update(TABLE, key, {**changes, "cap_nhat_luc": today}):
                counts["updated"] += 1
                pushed.append(row)
        elif key in drafts:
            if api.draft_update(TABLE, key, row):
                counts["updated"] += 1
        else:
            api.draft_create(TABLE, row)
            counts["created"] += 1
            pushed.append(row)

    for key, record in existing.items():
        if key in wanted or _s(record.get("nguon")) not in SOURCES or _s(record.get("trang_thai")) != OPEN:
            continue
        if api.draft_update(TABLE, key, {"trang_thai": DONE, "cap_nhat_luc": today}):
            counts["closed"] += 1
            pushed.append({**record, "trang_thai": DONE})
    for key, draft in drafts.items():  # an unsent new row whose condition already went away
        if key not in wanted and key not in existing and draft.op == "create" \
                and _s(draft.fields.get("trang_thai")) == OPEN:
            api.draft_update(TABLE, key, {"trang_thai": DONE, "cap_nhat_luc": today})
            counts["closed"] += 1
    if pushed:
        push_to_paperclip(api, pushed)
    return counts


def push_to_paperclip(api: Any, rows: list[dict[str, Any]]) -> bool:
    """Optional one-way push. UNVERIFIED: the endpoint and body are assumptions.

    Skipped without an address and token. ma_ngoai / dong_bo_luc are never sent or written."""
    base = api.config("paperclip_url").strip().rstrip("/")
    token = api.secret("paperclip_token")
    if not base or not token:
        return False
    tasks = [{k: v for k, v in r.items() if k not in ("ma_ngoai", "dong_bo_luc") and not k.startswith("_")}
             for r in rows]
    reply = api.http("POST", base + PUSH_PATH, {"tasks": tasks}, headers={"Authorization": f"Bearer {token}"},
                     record_ids=[t["ma_cv"] for t in tasks if t.get("ma_cv")])
    if not reply.ok:
        api.notify(f"Paperclip push failed (HTTP {reply.status}); the cong_viec table is unaffected.")
    return reply.ok


def on_after_commit(api: Any, changes: list[dict[str, Any]]) -> None:
    """A unique conflict on cong_viec means the row already exists: drop our draft, keep going."""
    if not changes:
        return
    exists: set[str] = set()
    for change in changes:
        if change["table"] == TABLE and change["status"] == "conflict":
            api.draft_discard(TABLE, change["key"])
            exists.add(change["key"])
    rebuild(api, frozenset(exists))


def register(api: Any) -> None:
    api.action("rebuild", lambda _payload: rebuild(api))
    api.on("after_commit", lambda changes: on_after_commit(api, changes))
