"""Section 7 rules: pure functions over cached tables. No network, no UI.

Input is a dict ``{table_key: [record_dict, ...]}`` where each record is the flat
field dict of a cached Teable row. Missing tables count as empty.

Text shown to users comes from the ``rules:`` section of labels_vi.yaml (``TEXTS``).
The constants in class ``V`` are stored data values defined by schema.yaml (choice
values and fixed codes), not UI text.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

DATA_DIR = Path(__file__).parent / "data"
TABLES = (
    "yeu_cau", "kien_truc", "nut", "phan_bo", "thong_so", "ung_vien", "doi_chieu",
    "mua_hang", "moc", "quyet_dinh", "sai_lech", "cai_dat", "rfq", "cong_viec",
)


class V:
    """Stored values from schema.yaml that the rules compare against."""

    YES = "Có"
    MUST = "Bắt buộc"
    CANCELLED = "Hủy"
    ARCH_CHOSEN = "Chọn"
    ARCH_REJECTED = "Loại"
    CAND_CHOSEN = "Chọn"
    CAND_REJECTED = "Loại"
    CHECK_PASS = "Đạt"
    CHECK_FAIL = "Không đạt"
    CHECK_UNSURE = "Không rõ"
    SPEC_NUMERIC = "Số"
    SPEC_QUAL = "Định tính"
    OEM = "Mua OEM"
    DERIVED = "Dẫn xuất"
    ALLOC_BUDGET = "Chia ngân sách"
    ALLOC_ONE = "Một nút gánh"
    ALLOC_SYSTEM = "Kiểm ở cấp hệ thống"
    RSS = "RSS"
    AI = "AI"
    SOURCING_CLOSED = "Đóng"
    SOURCING_NOT_ASKED = "Chưa hỏi"
    CHANGE_OPEN = "Mở"
    CHANGE_DONE = "Xong"
    MILESTONE = "G4a"


def load_texts(path: Path | None = None) -> dict[str, str]:
    """Return the ``rules:`` section of labels_vi.yaml as one flat mapping."""
    with open(path or DATA_DIR / "labels_vi.yaml", encoding="utf-8") as fh:
        section = (yaml.safe_load(fh) or {}).get("rules")
    if not isinstance(section, dict):
        raise ValueError("labels_vi.yaml has no 'rules:' section")
    return {str(k): str(v) for k, v in section.items()}


TEXTS: dict[str, str] = load_texts()

# Check rows
PASS, FAIL, UNCHECKED = "pass", "fail", "unchecked"
# Candidate results (display text is TEXTS["result_" + code])
RES_PASS, RES_FAIL_MUST, RES_INCOMPLETE = "pass", "fail_must", "incomplete"

# Next-action table rows (1-based, as in section 7) and their text codes.
ROW_CODES = {
    1: "wait_arch", 2: "wait_gate1", 3: "wait_gate2", 4: "write_specs", 5: "done",
    6: "chosen_failing", 7: "find_candidates", 8: "check_datasheets", 9: "none_passing",
    10: "wait_sourcing", 11: "choose",
}
OPEN_ROWS = frozenset({7, 8, 11})  # steps 3, 4 and 5: the leaf occupies its owner
ACTIONABLE_ROWS = frozenset({4, 6, 7, 8, 11})  # rows where the owner has work to do

COUNTER_ORDER = (
    "must_not_allocated", "pairs_missing_spec", "budget_rows_over",
    "passing_not_picked_up", "chosen_no_quote", "chosen_no_lead_time", "rows_with_warning",
)
SOON_DAYS = 14
RATE_KEY_PREFIX = "vnd_per_"  # cai_dat key = prefix + lower-case currency; value = VND per ONE unit
BASE_CURRENCY = "VND"
VND_PER_MILLION = 1_000_000
# Built in: VND is always 1. Old ty_gia_<CUR> rows (million VND per unit) are never read.
DEFAULT_RATES = {BASE_CURRENCY: 1.0}


# ---------------------------------------------------------------- small helpers

def to_million_vnd(amount: float, rate_vnd: float) -> float:
    """``amount`` in a currency worth ``rate_vnd`` VND per unit, as million VND."""
    return amount * rate_vnd / VND_PER_MILLION


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num(value: Any) -> float | None:
    text = _s(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = _s(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _split(value: Any) -> list[str]:
    return [p.strip() for p in _s(value).split(";") if p.strip()]


# ---------------------------------------------------------------- result types

@dataclass(frozen=True)
class Context:
    """Who is asking, about what, and when."""

    today: date = field(default_factory=date.today)
    user: str = ""
    node: str | None = None
    drafts: int = 0


@dataclass(frozen=True)
class NextAction:
    row: int  # 1..11 in the section 7 table
    code: str
    text: str
    step: int | None  # 2..5 for the numbered steps, else None
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Warn:
    code: str
    table: str
    key: str  # row ID in its table; "" for a table-level warning
    text: str
    node: str | None = None
    owner: str | None = None
    severity: str = "red"


@dataclass(frozen=True)
class BudgetTotal:
    ma_yc: str
    total: float
    limit: float | None
    margin: float | None
    over: bool
    method: str
    row_keys: tuple[str, ...]


# ---------------------------------------------------------------- the analysis

class Analysis:
    """All section 7 results for one snapshot of the cache."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]], ctx: Context | None = None):
        self.ctx = ctx or Context()
        self.t: dict[str, list[dict[str, Any]]] = {n: list(tables.get(n) or []) for n in TABLES}
        self.settings: dict[str, str] = {
            _s(r.get("khoa")): _s(r.get("gia_tri")) for r in self.t["cai_dat"] if _s(r.get("khoa"))
        }
        self.nodes: dict[str, dict[str, Any]] = {}
        for row in self.t["nut"]:
            self.nodes.setdefault(_s(row.get("ma_nut")), row)
        self.parent_codes = {_s(r.get("ma_cha")) for r in self.t["nut"] if _s(r.get("ma_cha"))}
        self.children: dict[str, list[str]] = defaultdict(list)
        for code, row in self.nodes.items():
            if _s(row.get("ma_cha")):
                self.children[_s(row["ma_cha"])].append(code)
        self.inactive = self._inactive_nodes()
        self.leaves = [c for c in self.nodes if c not in self.parent_codes and c not in self.inactive]

        self.specs_by_node = self._group("thong_so", "ma_nut")
        self.alloc_by_node = self._group("phan_bo", "ma_nut")
        self.cands_by_node = self._group("ung_vien", "ma_nut")
        self.cands = {_s(r.get("ma_uv")): r for r in self.t["ung_vien"]}
        self.specs = {_s(r.get("ma_ts")): r for r in self.t["thong_so"]}
        self.sourcing = {_s(r.get("ma_uv")): r for r in self.t["mua_hang"]}
        self.checks: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.t["doi_chieu"]:
            self.checks[self._check_pair(row)] = row
        self._result_cache: dict[str, str] = {}
        self._next_cache: dict[str, NextAction] = {}
        self._warnings: list[Warn] | None = None

    def _inactive_nodes(self) -> set[str]:
        """Nodes tagged (ma_kt) with an architecture that is rejected, and everything below them."""
        rejected = {_s(a.get("ma_kt")) for a in self.t["kien_truc"] if _s(a.get("trang_thai")) == V.ARCH_REJECTED}
        out = {c for c, r in self.nodes.items() if _s(r.get("ma_kt")) in rejected and _s(r.get("ma_kt"))}
        stack = list(out)
        while stack:
            for child in self.children.get(stack.pop(), []):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    # -- grouping and settings -------------------------------------------------

    def _group(self, table: str, column: str) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.t[table]:
            groups[_s(row.get(column))].append(row)
        return groups

    @staticmethod
    def _check_pair(row: dict[str, Any]) -> tuple[str, str]:
        uv, ts = _s(row.get("ma_uv")), _s(row.get("ma_ts"))
        if not (uv and ts) and "|" in _s(row.get("khoa")):
            uv, ts = (p.strip() for p in _s(row["khoa"]).split("|", 1))
        return uv, ts

    def gate(self, number: int) -> bool:
        return self.settings.get(f"chot_cap_{number}", "") == V.YES

    def setting_int(self, key: str, default: int) -> int:
        value = _num(self.settings.get(key))
        return int(value) if value is not None else default

    def owner_of(self, node: str | None) -> str | None:
        row = self.nodes.get(node or "")
        return (_s(row.get("phu_trach")) or None) if row else None

    # -- tree ------------------------------------------------------------------

    def level(self, node: str) -> int:
        """0 for the node with no parent, else 1 + number of dots in the code."""
        row = self.nodes.get(node, {})
        return 0 if not _s(row.get("ma_cha")) else 1 + node.count(".")

    def is_leaf(self, node: str) -> bool:
        return node in self.nodes and node not in self.parent_codes

    def leaf_descendants(self, node: str) -> list[str]:
        if self.is_leaf(node):
            return [node]
        out: list[str] = []
        seen = {node}
        stack = list(self.children.get(node, []))
        while stack:
            code = stack.pop(0)
            if code in seen:
                continue
            seen.add(code)
            if self.is_leaf(code):
                out.append(code)
            else:
                stack.extend(self.children.get(code, []))
        return out

    def progress(self, node: str) -> tuple[int, int]:
        """(leaves done, leaves total) under a node."""
        leaves = self.leaf_descendants(node)
        done = sum(1 for leaf in leaves if self.next_action(leaf).row == 5)
        return done, len(leaves)

    def progress_text(self, node: str) -> str:
        done, total = self.progress(node)
        return TEXTS["leaves_done"].format(x=done, y=total)

    # -- check rows and candidate results --------------------------------------

    def check_state(self, uv: str, ts: str) -> str:
        """pass, fail or unchecked for one candidate x specification cell."""
        row = self.checks.get((uv, ts))
        spec = self.specs.get(ts)
        if row is None or spec is None:
            return UNCHECKED
        hand = _s(row.get("danh_gia_tay"))
        if hand == V.CHECK_PASS:
            return PASS
        if hand == V.CHECK_FAIL:
            return FAIL
        if hand == V.CHECK_UNSURE:
            return UNCHECKED
        value = _num(row.get("gia_tri_so"))
        if _s(spec.get("kieu")) != V.SPEC_NUMERIC or value is None:
            return UNCHECKED
        low, high = _num(spec.get("gia_tri_min")), _num(spec.get("gia_tri_max"))
        if (low is not None and value < low) or (high is not None and value > high):
            return FAIL
        return PASS

    def candidate_result(self, uv: str) -> str:
        """RES_FAIL_MUST, RES_INCOMPLETE or RES_PASS."""
        if uv in self._result_cache:
            return self._result_cache[uv]
        node = _s(self.cands.get(uv, {}).get("ma_nut"))
        states = [
            (self.check_state(uv, _s(s.get("ma_ts"))), _s(s.get("muc")) == V.MUST)
            for s in self.specs_by_node.get(node, [])
        ]
        if any(state == FAIL and must for state, must in states):
            result = RES_FAIL_MUST
        elif any(state == UNCHECKED for state, _ in states):
            result = RES_INCOMPLETE
        else:
            result = RES_PASS
        self._result_cache[uv] = result
        return result

    def result_text(self, uv: str) -> str:
        return TEXTS["result_" + self.candidate_result(uv)]

    def active_candidates(self, node: str) -> list[str]:
        """Candidates of a node that are not rejected."""
        return [
            _s(c.get("ma_uv")) for c in self.cands_by_node.get(node, [])
            if _s(c.get("trang_thai")) != V.CAND_REJECTED
        ]

    def chosen_candidates(self, node: str) -> list[str]:
        return [
            _s(c.get("ma_uv")) for c in self.cands_by_node.get(node, [])
            if _s(c.get("trang_thai")) == V.CAND_CHOSEN
        ]

    def missing_cells(self, node: str) -> int:
        """Unchecked candidate x specification cells for non-rejected candidates."""
        specs = self.specs_by_node.get(node, [])
        return sum(
            1 for uv in self.active_candidates(node) for s in specs
            if self.check_state(uv, _s(s.get("ma_ts"))) == UNCHECKED
        )

    def passing_candidates(self, node: str) -> list[str]:
        return [uv for uv in self.active_candidates(node) if self.candidate_result(uv) == RES_PASS]

    def has_quote(self, uv: str) -> bool:
        return _num(self.sourcing.get(uv, {}).get("don_gia_bao")) is not None

    def has_lead_time(self, uv: str) -> bool:
        return _num(self.sourcing.get(uv, {}).get("tg_cho_tuan")) is not None

    def min_candidates(self, node: str) -> int:
        if _s(self.nodes.get(node, {}).get("loai")) == V.OEM:
            return self.setting_int("so_uv_toi_thieu", 3)
        return 1

    # -- next action -----------------------------------------------------------

    def next_action(self, node: str) -> NextAction:
        """Section 7 table, first match wins. Meant for leaves."""
        if node not in self._next_cache:
            self._next_cache[node] = self._compute_next(node)
        return self._next_cache[node]

    def _compute_next(self, node: str) -> NextAction:
        row, args = self._next_row(node)
        code = ROW_CODES[row]
        step = {4: 2, 7: 3, 8: 4, 11: 5}.get(row)
        return NextAction(row, code, TEXTS["next_" + code].format(**args), step, args)

    def _next_row(self, node: str) -> tuple[int, dict[str, Any]]:
        if sum(1 for a in self.t["kien_truc"] if _s(a.get("trang_thai")) == V.ARCH_CHOSEN) != 1:
            return 1, {}
        if not self.gate(1):
            return 2, {}
        if not self.gate(2):
            return 3, {}
        if not self.specs_by_node.get(node):
            allocated = {_s(a.get("ma_yc")) for a in self.alloc_by_node.get(node, [])}
            return 4, {"n": len(allocated)}
        chosen = self.chosen_candidates(node)
        if chosen:
            return (5, {}) if self.candidate_result(chosen[0]) == RES_PASS else (6, {})
        active = self.active_candidates(node)
        need = self.min_candidates(node)
        if len(active) < need:
            return 7, {"n": len(active), "m": need}
        missing = self.missing_cells(node)
        if missing:
            return 8, {"k": missing}
        passing = self.passing_candidates(node)
        if not passing:
            return 9, {}
        if not any(self.has_quote(uv) and self.has_lead_time(uv) for uv in passing):
            return 10, {}
        return 11, {}

    # -- price and cost --------------------------------------------------------

    def rate(self, currency: str) -> float | None:
        """VND per ONE unit of currency, from cai_dat (empty currency means VND, always 1)."""
        cur = (_s(currency) or BASE_CURRENCY).upper()
        if cur == BASE_CURRENCY:
            return DEFAULT_RATES[BASE_CURRENCY]
        value = _num(self.settings.get(f"{RATE_KEY_PREFIX}{cur.lower()}"))
        return value if value is not None and value > 0 else DEFAULT_RATES.get(cur)

    def price_used(self, uv: str) -> float | None:
        """Quoted price from mua_hang if present, else published price; million VND."""
        quote = self.sourcing.get(uv, {})
        amount, currency = _num(quote.get("don_gia_bao")), quote.get("tien_te")
        if amount is None:
            cand = self.cands.get(uv, {})
            amount, currency = _num(cand.get("gia_cong_bo")), cand.get("tien_te")
        rate = self.rate(currency or "")
        if amount is None or rate is None:
            return None
        return to_million_vnd(amount, rate)

    def node_cost(self, node: str) -> float:
        """Leaf = quantity x price of the chosen candidate; parent = sum of its leaves."""
        if not self.is_leaf(node):
            return sum(self.node_cost(leaf) for leaf in self.leaf_descendants(node))
        chosen = self.chosen_candidates(node)
        if not chosen:
            return 0.0
        price = self.price_used(chosen[0])
        quantity = _num(self.nodes[node].get("so_luong"))
        return (1.0 if quantity is None else quantity) * (price or 0.0)

    # -- budgets ---------------------------------------------------------------

    def budget_totals(self) -> dict[str, BudgetTotal]:
        """Per requirement: sum or root-sum-square of gia_tri_phan_bo of budget rows."""
        rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.t["phan_bo"]:
            if _s(r.get("kieu")) == V.ALLOC_BUDGET:
                rows[_s(r.get("ma_yc"))].append(r)
        out: dict[str, BudgetTotal] = {}
        for yc, group in rows.items():
            values = [v for v in (_num(r.get("gia_tri_phan_bo")) for r in group) if v is not None]
            method = next((_s(r.get("cach_cong")) for r in group if _s(r.get("cach_cong"))), "")
            if method == V.RSS:
                total = math.sqrt(sum(v * v for v in values))
            else:
                total = float(sum(values))
            limits = [v for v in (_num(r.get("gioi_han_he_thong")) for r in group) if v is not None]
            limit = max(limits) if limits else None
            over = limit is not None and total > limit + 1e-9
            out[yc] = BudgetTotal(
                yc, total, limit, None if limit is None else limit - total, over, method,
                tuple(_s(r.get("ma_pb")) for r in group),
            )
        return out

    # -- sourcing dates ---------------------------------------------------------

    def milestone_date(self) -> date | None:
        for row in self.t["moc"]:
            if _s(row.get("ma_moc")) == V.MILESTONE:
                return _date(row.get("ngay_du_bao")) or _date(row.get("ngay_co_so"))
        return None

    def decision_date(self) -> date | None:
        """Latest forecast date of an unresolved decision that serves the milestone."""
        dates = [
            _date(r.get("ngay_du_bao")) for r in self.t["quyet_dinh"]
            if _s(r.get("phuc_vu_moc")) == V.MILESTONE and not _s(r.get("ket_luan"))
        ]
        dates = [d for d in dates if d]
        return max(dates) if dates else None

    def order_by(self, uv: str) -> date | None:
        """Date of milestone G4a minus the lead time."""
        milestone = self.milestone_date()
        weeks = _num(self.sourcing.get(uv, {}).get("tg_cho_tuan"))
        if milestone is None or weeks is None:
            return None
        return milestone - timedelta(weeks=weeks)

    def sourcing_queue(self) -> list[str]:
        """Passing candidates (not rejected) with no mua_hang row yet: the 'Chờ nhận' list."""
        return [
            _s(c.get("ma_uv")) for c in self.t["ung_vien"]
            if _s(c.get("trang_thai")) != V.CAND_REJECTED
            and self.candidate_result(_s(c.get("ma_uv"))) == RES_PASS
            and _s(c.get("ma_uv")) not in self.sourcing
        ]

    # -- counters --------------------------------------------------------------

    def pairs_missing_spec(self) -> list[tuple[str, str]]:
        """(ma_yc, ma_nut) pairs on a leaf that has specifications but none for that requirement.

        Pairs of kind 'Kiểm ở cấp hệ thống' are checked at system level and are skipped.
        """
        pairs: list[tuple[str, str]] = []
        for node in self.leaves:
            specs = self.specs_by_node.get(node)
            if not specs:
                continue
            covered = {_s(s.get("ma_yc_goc")) for s in specs}
            seen: set[str] = set()
            for alloc in self.alloc_by_node.get(node, []):
                yc = _s(alloc.get("ma_yc"))
                if _s(alloc.get("kieu")) == V.ALLOC_SYSTEM or yc in covered or yc in seen:
                    continue
                seen.add(yc)
                pairs.append((yc, node))
        return pairs

    def counters(self) -> dict[str, int]:
        allocated = {_s(r.get("ma_yc")) for r in self.t["phan_bo"]}
        over_requirements = {yc for yc, b in self.budget_totals().items() if b.over}
        chosen = [
            _s(c.get("ma_uv")) for c in self.t["ung_vien"] if _s(c.get("trang_thai")) == V.CAND_CHOSEN
        ]
        return {
            "must_not_allocated": sum(
                1 for r in self.t["yeu_cau"]
                if _s(r.get("muc")) == V.MUST and _s(r.get("trang_thai")) != V.CANCELLED
                and _s(r.get("ma_yc")) not in allocated
            ),
            "pairs_missing_spec": len(self.pairs_missing_spec()),
            "budget_rows_over": sum(
                1 for r in self.t["phan_bo"]
                if _s(r.get("kieu")) == V.ALLOC_BUDGET and _s(r.get("ma_yc")) in over_requirements
            ),
            "passing_not_picked_up": len(self.sourcing_queue()),
            "chosen_no_quote": sum(1 for uv in chosen if not self.has_quote(uv)),
            "chosen_no_lead_time": sum(1 for uv in chosen if not self.has_lead_time(uv)),
            "rows_with_warning": len({(w.table, w.key) for w in self.warnings()}),
        }

    def counters_labeled(self) -> list[tuple[str, str, int]]:
        values = self.counters()
        return [(name, TEXTS["counter_" + name], values[name]) for name in COUNTER_ORDER]

    # -- warnings --------------------------------------------------------------

    def warnings(self) -> list[Warn]:
        if self._warnings is None:
            out: list[Warn] = []
            for part in (
                self._req_warnings, self._tree_warnings, self._one_node_warnings, self._arch_warnings,
                self._alloc_warnings, self._spec_warnings, self._cand_warnings,
                self._check_warnings, self._sourcing_warnings, self._finding_warnings,
            ):
                out.extend(part())
            self._warnings = out
        return self._warnings

    def warnings_for(self, table: str, key: str) -> list[Warn]:
        return [w for w in self.warnings() if w.table == table and w.key == key]

    def _w(self, code: str, table: str, key: str, node: str | None = None) -> Warn:
        return Warn(code, table, key, TEXTS["warn_" + code], node, self.owner_of(node))

    def _tree_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        roots = [c for c, r in self.nodes.items() if not _s(r.get("ma_cha"))]
        for code, row in self.nodes.items():
            parent = _s(row.get("ma_cha"))
            if parent and parent not in self.nodes:
                out.append(self._w("tree_parent_missing", "nut", code, code))
            if self.level(code) > 2:
                out.append(self._w("tree_too_deep", "nut", code, code))
            if not parent and len(roots) > 1:
                out.append(self._w("tree_multi_root", "nut", code, code))
            if "." in code and parent != code.rsplit(".", 1)[0]:
                out.append(self._w("tree_bad_parent", "nut", code, code))
            if not self.gate(2) and (self.specs_by_node.get(code) or self.cands_by_node.get(code)):
                out.append(self._w("tree_too_early", "nut", code, code))
            if self.gate(2) and self.is_leaf(code) and not _s(row.get("phu_trach")):
                out.append(self._w("tree_leaf_no_owner", "nut", code, code))
        return out

    def _one_node_warnings(self) -> list[Warn]:
        by_owner: dict[str, list[str]] = defaultdict(list)
        for leaf in self.leaves:
            owner = self.owner_of(leaf)
            if owner and self.next_action(leaf).row in OPEN_ROWS:
                by_owner[owner].append(leaf)
        return [
            self._w("one_node_at_a_time", "nut", leaf, leaf)
            for leaves in by_owner.values() if len(leaves) >= 2 for leaf in leaves
        ]

    def _req_warnings(self) -> list[Warn]:
        """A must-have requirement that is not retired needs an acceptance criterion."""
        out: list[Warn] = []
        for row in self.t["yeu_cau"]:
            must = _s(row.get("muc")) == V.MUST
            retired = _s(row.get("trang_thai")) == V.CANCELLED
            if must and not retired and not _s(row.get("tieu_chi_nghiem_thu")):
                out.append(self._w("req_no_criterion", "yeu_cau", _s(row.get("ma_yc"))))
        return out

    def _arch_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        rows = self.t["kien_truc"]
        if len(rows) < 2:
            out.append(self._w("arch_too_few", "kien_truc", ""))
        for row in rows:
            status = _s(row.get("trang_thai"))
            if status in (V.ARCH_CHOSEN, V.ARCH_REJECTED) and not _s(row.get("ly_do")):
                out.append(self._w("arch_no_reason", "kien_truc", _s(row.get("ma_kt"))))
        chosen = [_s(r.get("ma_kt")) for r in rows if _s(r.get("trang_thai")) == V.ARCH_CHOSEN]
        if len(chosen) > 1:
            out.extend(self._w("arch_multi_chosen", "kien_truc", code) for code in chosen)
        return out

    def _finding_warnings(self) -> list[Warn]:
        """An open change card or review finding with nobody assigned is seen by no one."""
        out: list[Warn] = []
        for row in self.t["sai_lech"]:
            is_open = _s(row.get("trang_thai")) in ("", V.CHANGE_OPEN)
            if is_open and not _s(row.get("nguoi_nhan")):
                node = _s(row.get("ma_nut")) or None
                out.append(self._w("finding_no_owner", "sai_lech", _s(row.get("ma_sl")), node))
        return out

    def _alloc_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        rows = self.t["phan_bo"]
        pair_count: dict[tuple[str, str], int] = defaultdict(int)
        by_yc: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            pair_count[(_s(r.get("ma_yc")), _s(r.get("ma_nut")))] += 1
            by_yc[_s(r.get("ma_yc"))].append(r)
        budgets = self.budget_totals()
        missing = set(self.pairs_missing_spec())
        for r in rows:
            key, yc, node, kind = _s(r.get("ma_pb")), _s(r.get("ma_yc")), _s(r.get("ma_nut")), _s(r.get("kieu"))
            if pair_count[(yc, node)] > 1:
                out.append(self._w("alloc_duplicate", "phan_bo", key, node))
            if node in self.nodes and not self.is_leaf(node) and kind != V.ALLOC_SYSTEM:
                out.append(self._w("alloc_type_nonleaf", "phan_bo", key, node))
            if kind == V.ALLOC_BUDGET and not (
                _num(r.get("gia_tri_phan_bo")) is not None
                and _num(r.get("gioi_han_he_thong")) is not None
                and _s(r.get("cach_cong"))
            ):
                out.append(self._w("alloc_budget_incomplete", "phan_bo", key, node))
            limits = {_num(x.get("gioi_han_he_thong")) for x in by_yc[yc]} - {None}
            if len(limits) > 1:
                out.append(self._w("alloc_limit_differs", "phan_bo", key, node))
            if kind == V.ALLOC_BUDGET and yc in budgets and budgets[yc].over:
                out.append(self._w("alloc_budget_over", "phan_bo", key, node))
            if kind == V.ALLOC_ONE and len([x for x in by_yc[yc] if _s(x.get("kieu")) == V.ALLOC_ONE]) > 1:
                out.append(self._w("alloc_single_many", "phan_bo", key, node))
            if (yc, node) in missing:
                out.append(self._w("alloc_missing_spec", "phan_bo", key, node))
        return out

    def _spec_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        requirements = {_s(r.get("ma_yc")) for r in self.t["yeu_cau"]}
        allocated = {(_s(r.get("ma_yc")), _s(r.get("ma_nut"))) for r in self.t["phan_bo"]}
        for r in self.t["thong_so"]:
            key, node, source = _s(r.get("ma_ts")), _s(r.get("ma_nut")), _s(r.get("ma_yc_goc"))
            kind = _s(r.get("kieu"))
            if kind == V.SPEC_NUMERIC and _num(r.get("gia_tri_min")) is None and _num(r.get("gia_tri_max")) is None:
                out.append(self._w("spec_numeric_no_bounds", "thong_so", key, node))
            if kind == V.SPEC_QUAL and not _s(r.get("mong_doi")):
                out.append(self._w("spec_qual_no_expected", "thong_so", key, node))
            if not _s(r.get("muc")) or not source:
                out.append(self._w("spec_missing_level_or_source", "thong_so", key, node))
            if source and source != V.DERIVED:
                if source not in requirements:
                    out.append(self._w("spec_source_unknown", "thong_so", key, node))
                if (source, node) not in allocated:
                    out.append(self._w("spec_pair_not_allocated", "thong_so", key, node))
            if node in self.nodes and not self.is_leaf(node):
                out.append(self._w("spec_on_nonleaf", "thong_so", key, node))
        return out

    def _cand_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        maximum = self.setting_int("so_uv_toi_da", 5)
        for node, rows in self.cands_by_node.items():
            chosen = self.chosen_candidates(node)
            active = self.active_candidates(node)
            for r in rows:
                uv, status = _s(r.get("ma_uv")), _s(r.get("trang_thai"))
                if not _s(r.get("link_datasheet")):
                    out.append(self._w("cand_no_datasheet", "ung_vien", uv, node))
                if not _s(r.get("ngay_kiem_tra")):
                    out.append(self._w("cand_no_date", "ung_vien", uv, node))
                if status == V.CAND_CHOSEN and self.candidate_result(uv) != RES_PASS:
                    out.append(self._w("cand_chosen_failing", "ung_vien", uv, node))
                if status == V.CAND_CHOSEN and len(chosen) > 1:
                    out.append(self._w("cand_two_chosen", "ung_vien", uv, node))
                if status in (V.CAND_CHOSEN, V.CAND_REJECTED) and not _s(r.get("ly_do")):
                    out.append(self._w("cand_no_reason", "ung_vien", uv, node))
                if status == V.CAND_CHOSEN and _s(r.get("nguoi_tim")) == V.AI and not _s(r.get("nguoi_kiem_lai")):
                    out.append(self._w("cand_ai_unchecked", "ung_vien", uv, node))
                if uv in active[maximum:]:
                    out.append(self._w("cand_too_many", "ung_vien", uv, node))
        return out

    def _check_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        for r in self.t["doi_chieu"]:
            uv, ts = self._check_pair(r)
            key = _s(r.get("khoa")) or f"{uv}|{ts}"
            cand_node = _s(self.cands.get(uv, {}).get("ma_nut"))
            spec_node = _s(self.specs.get(ts, {}).get("ma_nut"))
            if uv in self.cands and ts in self.specs and cand_node != spec_node:
                out.append(self._w("check_node_mismatch", "doi_chieu", key, cand_node))
            has_result = _s(r.get("danh_gia_tay")) in (V.CHECK_PASS, V.CHECK_FAIL) or _num(r.get("gia_tri_so")) is not None
            if has_result and not (_s(r.get("trich_dan")) and _s(r.get("trang"))):
                out.append(self._w("check_no_citation", "doi_chieu", key, cand_node or None))
        return out

    def _sourcing_warnings(self) -> list[Warn]:
        out: list[Warn] = []
        today = self.ctx.today
        decision = self.decision_date()
        for r in self.t["mua_hang"]:
            uv = _s(r.get("ma_uv"))
            cand = self.cands.get(uv, {})
            node = _s(cand.get("ma_nut")) or None
            rejected = _s(cand.get("trang_thai")) == V.CAND_REJECTED
            if rejected and _s(r.get("trang_thai_mua")) != V.SOURCING_CLOSED:
                out.append(self._w("src_rejected_open", "mua_hang", uv, node))
            if rejected:
                continue
            if _s(r.get("tinh_trang_nguon")) in ("", V.SOURCING_NOT_ASKED):
                out.append(self._w("src_no_availability", "mua_hang", uv, node))
            if _num(r.get("tg_cho_tuan")) is None:
                out.append(self._w("src_no_lead_time", "mua_hang", uv, node))
            expiry = _date(r.get("bao_gia_het_han"))
            if expiry is not None and expiry < today:
                out.append(self._w("src_quote_expired", "mua_hang", uv, node))
            deadline = self.order_by(uv)
            if deadline is None:
                continue
            if deadline < today:
                out.append(self._w("src_order_passed", "mua_hang", uv, node))
            elif deadline <= today + timedelta(days=SOON_DAYS):
                out.append(self._w("src_order_soon", "mua_hang", uv, node))
            if decision is not None and deadline < decision:
                out.append(self._w("src_order_before_decision", "mua_hang", uv, node))
        return out


def analyse(tables: dict[str, list[dict[str, Any]]], ctx: Context | None = None) -> Analysis:
    """Entry point for the app and plugins (api.rules())."""
    return Analysis(tables, ctx)


# ---------------------------------------------------------------- decision tree checks
# Each check takes an Analysis (or raw tables plus ctx) and returns True, False, or
# None when it cannot be answered (for example no node selected).

CheckFn = Callable[[Analysis], "bool | None"]
CHECKS: dict[str, CheckFn] = {}
NODE_CHECKS: set[str] = set()


def _check(name: str, needs_node: bool = False) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[name] = fn
        if needs_node:
            NODE_CHECKS.add(name)
        return fn

    return register


def run_check(name: str, data: Analysis | dict[str, list[dict[str, Any]]], ctx: Context | None = None) -> bool | None:
    """Run one named check on cached tables (or a ready Analysis)."""
    if name not in CHECKS:
        raise KeyError(f"unknown check '{name}'")
    analysis = data if isinstance(data, Analysis) else Analysis(data, ctx)
    return CHECKS[name](analysis)


def _selected_leaf(a: Analysis) -> str | None:
    node = a.ctx.node
    return node if node and a.is_leaf(node) else None


def _owned_leaves(a: Analysis) -> list[str]:
    return [leaf for leaf in a.leaves if a.owner_of(leaf) == a.ctx.user] if a.ctx.user else []


@_check("requirements_complete")
def requirements_complete(a: Analysis) -> bool:
    live = [r for r in a.t["yeu_cau"] if _s(r.get("trang_thai")) != V.CANCELLED]
    return bool(live) and all(_s(r.get("ma_yc")) and _s(r.get("muc")) for r in live)


@_check("two_architectures")
def two_architectures(a: Analysis) -> bool:
    return len(a.t["kien_truc"]) >= 2


@_check("one_architecture_chosen")
def one_architecture_chosen(a: Analysis) -> bool:
    chosen = [r for r in a.t["kien_truc"] if _s(r.get("trang_thai")) == V.ARCH_CHOSEN]
    return len(chosen) == 1 and bool(_s(chosen[0].get("ly_do")))


@_check("gate_level_1")
def gate_level_1(a: Analysis) -> bool:
    return a.gate(1)


@_check("gate_level_2")
def gate_level_2(a: Analysis) -> bool:
    return a.gate(2)


@_check("all_must_allocated")
def all_must_allocated(a: Analysis) -> bool:
    return a.counters()["must_not_allocated"] == 0 and any(
        _s(r.get("muc")) == V.MUST for r in a.t["yeu_cau"]
    )


@_check("budget_over")
def budget_over(a: Analysis) -> bool:
    return any(b.over for b in a.budget_totals().values())


@_check("leaves_assigned")
def leaves_assigned(a: Analysis) -> bool:
    return bool(a.leaves) and all(a.owner_of(leaf) for leaf in a.leaves)


@_check("any_node_stuck")
def any_node_stuck(a: Analysis) -> bool:
    return any(a.next_action(leaf).row == 9 for leaf in a.leaves)


@_check("other_node_open", needs_node=True)
def other_node_open(a: Analysis) -> bool | None:
    if _selected_leaf(a) is None:
        return None
    return any(
        leaf != a.ctx.node and a.next_action(leaf).row in OPEN_ROWS for leaf in _owned_leaves(a)
    )


@_check("node_specs_cover_allocation", needs_node=True)
def node_specs_cover_allocation(a: Analysis) -> bool | None:
    node = _selected_leaf(a)
    if node is None:
        return None
    specs = a.specs_by_node.get(node, [])
    covered = {_s(s.get("ma_yc_goc")) for s in specs}
    needed = {
        _s(p.get("ma_yc")) for p in a.alloc_by_node.get(node, []) if _s(p.get("kieu")) != V.ALLOC_SYSTEM
    }
    return bool(specs) and needed <= covered


@_check("node_enough_candidates", needs_node=True)
def node_enough_candidates(a: Analysis) -> bool | None:
    node = _selected_leaf(a)
    if node is None:
        return None
    return len(a.active_candidates(node)) >= a.min_candidates(node)


@_check("node_checks_complete", needs_node=True)
def node_checks_complete(a: Analysis) -> bool | None:
    node = _selected_leaf(a)
    if node is None:
        return None
    return bool(a.specs_by_node.get(node)) and bool(a.active_candidates(node)) and a.missing_cells(node) == 0


@_check("node_has_passing_candidate", needs_node=True)
def node_has_passing_candidate(a: Analysis) -> bool | None:
    node = _selected_leaf(a)
    return None if node is None else bool(a.passing_candidates(node))


@_check("node_sourcing_answered", needs_node=True)
def node_sourcing_answered(a: Analysis) -> bool | None:
    node = _selected_leaf(a)
    if node is None:
        return None
    return any(a.has_quote(uv) and a.has_lead_time(uv) for uv in a.passing_candidates(node))


@_check("has_drafts")
def has_drafts(a: Analysis) -> bool:
    return a.ctx.drafts > 0


@_check("my_warnings")
def my_warnings(a: Analysis) -> bool:
    return bool(a.ctx.user) and any(w.owner == a.ctx.user and w.severity == "red" for w in a.warnings())


@_check("my_change_cards")
def my_change_cards(a: Analysis) -> bool:
    return bool(a.ctx.user) and any(
        _s(r.get("nguoi_nhan")) == a.ctx.user and _s(r.get("trang_thai")) in ("", V.CHANGE_OPEN)
        for r in a.t["sai_lech"]
    )


@_check("my_next_actions")
def my_next_actions(a: Analysis) -> bool:
    return any(a.next_action(leaf).row in ACTIONABLE_ROWS for leaf in _owned_leaves(a))


@_check("counters_zero")
def counters_zero(a: Analysis) -> bool:
    return all(v == 0 for v in a.counters().values())
