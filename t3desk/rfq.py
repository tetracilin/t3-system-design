"""RFQ and RFP payload builder (section 9.2).

The payload that leaves the machine never holds another vendor's quoted price, the budget or
any score. ``assert_clean`` checks the finished payload by key name as a second line of defence;
the builder itself only copies the fields listed here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from t3desk import rules
from t3desk.plugins_api import PluginApi

KIND_RFQ, KIND_RFP = "RFQ", "RFP"
STATUS_DRAFT = "Nháp"  # value of the schema choice rfq.trang_thai, not UI text
# Key-name tokens that mean price, budget or score. A payload key holding one is a bug.
FORBIDDEN_TOKENS = frozenset({"gia", "price", "budget", "score", "diem", "cost", "sach", "quote"})
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


class RfqError(Exception):
    pass


class ExtraConfirmationRequired(RfqError):
    """A selected candidate is not Đạt; the user must confirm separately."""

    def __init__(self, candidates: list[tuple[str, str]]):
        self.candidates = candidates
        super().__init__("candidates that are not Đạt need an extra confirmation: "
                         + ", ".join(f"{uv} ({res})" for uv, res in candidates))


class ForbiddenContent(RfqError):
    pass


def forbidden_paths(payload: Any, path: str = "") -> list[str]:
    """Paths of dict keys that name a price, budget or score."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else str(key)
            if set(_TOKEN_SPLIT.split(str(key).lower())) & FORBIDDEN_TOKENS:
                found.append(here)
            found.extend(forbidden_paths(value, here))
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            found.extend(forbidden_paths(value, f"{path}[{i}]"))
    return found


def assert_clean(payload: dict[str, Any]) -> None:
    bad = forbidden_paths(payload)
    if bad:
        raise ForbiddenContent("payload would carry price, budget or score fields: " + ", ".join(bad))


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num_text(value: Any) -> str:
    number = rules._num(value)
    if number is None:
        return ""
    return str(int(number)) if number == int(number) else str(number)


def requirement_text(spec: dict[str, Any]) -> str:
    """The need in one line: ``>= 10 MPa``, ``<= 5 kg``, ``10 - 20 MHz`` or the expected text."""
    unit = _s(spec.get("don_vi"))
    low, high = _num_text(spec.get("gia_tri_min")), _num_text(spec.get("gia_tri_max"))
    if _s(spec.get("kieu")) == rules.V.SPEC_QUAL or (not low and not high):
        return _s(spec.get("mong_doi"))
    if low and high:
        text = f"{low} - {high}"
    elif low:
        text = f"≥ {low}"
    else:
        text = f"≤ {high}"
    return f"{text} {unit}".strip()


def _spec_items(a: rules.Analysis, node: str) -> list[dict[str, str]]:
    return [
        {"ma_ts": _s(s.get("ma_ts")), "thong_so": _s(s.get("thong_so")),
         "yeu_cau": requirement_text(s), "muc": _s(s.get("muc"))}
        for s in a.specs_by_node.get(node, [])
    ]


def non_passing(a: rules.Analysis, ma_uv: Iterable[str]) -> list[tuple[str, str]]:
    """(candidate, result text) for each selected candidate whose result is not Đạt."""
    return [(uv, a.result_text(uv)) for uv in ma_uv if a.candidate_result(uv) != rules.RES_PASS]


def _item(a: rules.Analysis, uv: str) -> dict[str, Any]:
    cand = a.cands.get(uv)
    if cand is None:
        raise RfqError(f"candidate {uv} is not in the cache")
    node = _s(cand.get("ma_nut"))
    node_row = a.nodes.get(node, {})
    return {
        "ma_uv": uv, "ma_nut": node, "ten_nut": _s(node_row.get("ten")), "hang": _s(cand.get("hang")),
        "model": _s(cand.get("model")), "cau_hinh": _s(cand.get("cau_hinh")),
        "so_luong": rules._num(node_row.get("so_luong")) or 1, "specs": _spec_items(a, node),
    }


def _node_block(a: rules.Analysis, node: str) -> dict[str, Any]:
    row = a.nodes.get(node)
    if row is None:
        raise RfqError(f"node {node} is not in the cache")
    requirements = {_s(r.get("ma_yc")): r for r in a.t["yeu_cau"]}
    seen: list[str] = []
    for alloc in a.alloc_by_node.get(node, []):  # codes only: the allocated values are budget shares
        code = _s(alloc.get("ma_yc"))
        if code and code not in seen:
            seen.append(code)
    return {
        "ma_nut": node, "ten": _s(row.get("ten")), "chuc_nang": _s(row.get("chuc_nang")),
        "yeu_cau": [
            {"ma_yc": c, "mo_ta": _s(requirements.get(c, {}).get("mo_ta")),
             "tieu_chi_nghiem_thu": _s(requirements.get(c, {}).get("tieu_chi_nghiem_thu"))}
            for c in seen
        ],
        "specs": _spec_items(a, node),
    }


def build_payload(
    a: rules.Analysis, *, kind: str, ma_rfq: str, requested_by: str, reply_by: str | None,
    vendor: str | None = None, ma_uv: Iterable[str] = (), ma_nut: str | None = None, language: str = "vi",
) -> dict[str, Any]:
    """The JSON of section 9.2. RFQ needs candidates; RFP needs a node and has empty ``items``."""
    if kind not in (KIND_RFQ, KIND_RFP):
        raise RfqError(f"kind must be RFQ or RFP, got {kind!r}")
    uvs = list(ma_uv)
    if kind == KIND_RFQ and not uvs:
        raise RfqError("an RFQ needs at least one candidate")
    if kind == KIND_RFP and not ma_nut:
        raise RfqError("an RFP needs a node")
    milestone = a.milestone_date()
    payload: dict[str, Any] = {
        "kind": kind, "ma_rfq": ma_rfq, "project": a.settings.get("ten_du_an", ""),
        "requested_by": requested_by, "language": language, "reply_by": reply_by,
        "need_by": milestone.isoformat() if milestone else None, "vendor": vendor or None,
        "items": [_item(a, uv) for uv in uvs] if kind == KIND_RFQ else [],
        "node": _node_block(a, ma_nut) if kind == KIND_RFP and ma_nut else None,
    }
    assert_clean(payload)
    return payload


@dataclass(frozen=True)
class RfqStart:
    ma_rfq: str
    payload: dict[str, Any]


def start_rfq(
    api: PluginApi, *, kind: str, ma_uv: Iterable[str] = (), ma_nut: str | None = None,
    vendor: str | None = None, reply_by: date | str | None = None,
    extra_confirm: Callable[[list[tuple[str, str]]], bool] | None = None,
) -> RfqStart:
    """Steps 1 of 9.2: propose an ID, build the payload and create the ``rfq`` draft.

    Raises ExtraConfirmationRequired when a selected candidate is not Đạt and ``extra_confirm``
    does not approve. Nothing is created in that case."""
    uvs = list(ma_uv)
    a = api.rules()
    risky = non_passing(a, uvs) if kind == KIND_RFQ else []
    if risky and not (extra_confirm and extra_confirm(risky)):
        raise ExtraConfirmationRequired(risky)
    ma_rfq = api.next_id("rfq", prefix=f"{kind}-")
    if ma_rfq is None:
        raise RfqError("cannot propose an rfq ID")
    reply = reply_by.isoformat() if isinstance(reply_by, date) else reply_by
    payload = build_payload(a, kind=kind, ma_rfq=ma_rfq, requested_by=api.user, reply_by=reply,
                            vendor=vendor, ma_uv=uvs, ma_nut=ma_nut)
    nodes = sorted({i["ma_nut"] for i in payload["items"]}) or ([ma_nut] if ma_nut else [])
    fields: dict[str, Any] = {"ma_rfq": ma_rfq, "loai": kind, "ds_ma_nut": ";".join(nodes),
                              "trang_thai": STATUS_DRAFT}
    if uvs:
        fields["ds_ma_uv"] = ";".join(uvs)
    if vendor:
        fields["nha_cung_cap"] = vendor
    if reply:
        fields["han_tra_loi"] = reply
    api.draft_create("rfq", fields)
    return RfqStart(ma_rfq, payload)
