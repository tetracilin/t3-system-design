"""Local web server: serves t3desk/ui and a JSON API over store, commit, rules and teable_client.

The server listens on 127.0.0.1 on a random free port. Every /api call must carry the
per-run session header that index.html receives, and the Host header must be the loopback
address, so another web page in the user's browser cannot drive the API.

``App`` holds all the logic and knows nothing about HTTP; ``make_server`` wraps it.
UI text never lives here: errors carry a machine ``code`` and the server's own detail, and
the UI maps the code to a Vietnamese label from labels_ui_vi.yaml.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import logging.handlers
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from t3desk import commit as commit_mod
from t3desk import decision_tree, platform, rules
from t3desk import schema as schema_mod
from t3desk import validation
from t3desk.bootstrap import BootstrapError, run_bootstrap
from t3desk.store import Draft, Store, load_secret, save_secret
from t3desk.teable_client import TeableClient, TeableConnectionError, TeableError, UniqueFlagError

log = logging.getLogger("t3desk.server")

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_LABELS = schema_mod.DATA_DIR / "labels_ui_vi.yaml"
STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "tree.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
SESSION_HEADER = "X-T3-Session"
SESSION_PLACEHOLDER = "__SESSION__"
SECRET_SERVICE = "t3desk"
SECRET_NAME = "teable"
MAX_BODY = 5_000_000

ROLES = ("system_designer", "designer", "engineer", "sourcing", "pm")
SYSTEM_DESIGNER = "system_designer"
# Role decides the first decision-tree tab and the first screen (section 2); it never blocks reading.
ROLE_TREE = {
    "system_designer": "system_design", "designer": "designer", "engineer": "engineer",
    "sourcing": "engineer", "pm": "engineer",
}
ROLE_SCREEN = {
    "system_designer": "yeu_cau", "designer": "nut", "engineer": "tong_quan",
    "sourcing": "mua_hang", "pm": "moc",
}
SCREENS = (
    "khoi_tao", "tong_quan", "ra_soat", "yeu_cau", "kien_truc", "cay", "phan_bo", "nut",
    "mua_hang", "rfq", "moc", "commit",
)
# Restricted to the System designer (section 2): the two gates and choosing an architecture.
GATE_KEYS = ("chot_cap_1", "chot_cap_2")
REVIEW_KEY = "ngay_ra_soat_cuoi"  # cai_dat row: when the last weekly review ended (Teable's clock)
REVIEW_CYCLE_KEY = "chu_ky_ra_soat_ngay"
REVIEW_CYCLE_DEFAULT = 7
REVIEW_SKIP_TABLES = ("cai_dat", "cong_viec")  # not reviewed: settings and the app's own task rows
CHANGE_CARD_RETIRE_ROLES = (SYSTEM_DESIGNER, "pm")  # who may set a change card or finding to Hủy
GATE_OFF = "Không"  # stored value of an open gate (schema data value, not UI text)
WEIGHT_KEYS = ("trong_so_ky_thuat", "trong_so_nguon_hang", "trong_so_thoi_gian")
SCORE_FIELDS = ("diem_ky_thuat", "diem_nguon_hang", "diem_thoi_gian")
MAX_LIST_COLUMNS = 9


class ApiError(Exception):
    """An error the UI can show: HTTP status, a stable code, and the server's own detail."""

    def __init__(self, status: int, code: str, detail: str = "", **extra: Any):
        super().__init__(f"{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "detail": self.detail, **self.extra}}


def load_ui_labels() -> dict[str, Any]:
    """labels_vi.yaml plus the ``ui`` section from labels_ui_vi.yaml (its own keys win only if absent)."""
    labels = schema_mod.load_labels()
    ui_file = schema_mod.load_yaml(UI_LABELS) if UI_LABELS.exists() else {}
    merged = dict(ui_file.get("ui", {}))
    merged.update(labels.get("ui", {}))
    labels["ui"] = merged
    return labels


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def natural_key(code: str) -> list[Any]:
    """Sort N1.2 before N1.10 and N2."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", code)]


def flatten(record: dict[str, Any]) -> dict[str, Any]:
    """A cached Teable record as the flat field dict the rules read, plus underscore metadata."""
    row = dict(record.get("fields", {}))
    row["_record_id"] = record.get("id")
    row["_modified"] = record.get("lastModifiedTime")
    row["_created"] = record.get("createdTime")
    return row


class App:
    """All screens' data and actions. One instance per run."""

    def __init__(
        self,
        home: Path | str,
        *,
        tree_path: Path | str | None = None,
        client_factory: Callable[..., TeableClient] | None = None,
        today: Callable[[], date] = date.today,
        keyring_module: Any = False,
    ):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.home / "t3desk.sqlite")
        self.schema = schema_mod.load_schema()
        self.labels = load_ui_labels()
        self.id_names = schema_mod.id_fields(self.schema)
        self.tree_store = decision_tree.TreeStore(tree_path)
        self.session = secrets.token_urlsafe(24)
        self._client_factory = client_factory or self._default_client
        self._today = today
        self._keyring = keyring_module  # False: use the OS keyring; None: restricted file only (tests)
        self._lock = threading.RLock()
        self._rev = 0
        self._analysis_cache: dict[tuple[Any, ...], rules.Analysis] = {}
        self._token: str | None = None
        self._client: TeableClient | None = None
        self._client_key: tuple[str, str] | None = None
        self._conn: dict[str, Any] | None = None
        self._conn_at = 0.0
        self.progress: dict[str, Any] = {}
        self.routes = self._build_routes()

    # ---- plumbing -----------------------------------------------------------

    @staticmethod
    def _default_client(url: str, token: str, *, retries: int = 1, timeout: float = 15.0) -> TeableClient:
        return TeableClient(url, token, retries=retries, timeout=timeout, backoff=0.3)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
        self.store.close()

    def _bump(self) -> None:
        with self._lock:
            self._rev += 1
            self._analysis_cache.clear()

    def setting(self, key: str, default: Any = None) -> Any:
        return self.store.get_setting(key, default)

    @property
    def user(self) -> str:
        return str(self.setting("user", "") or "")

    @property
    def role(self) -> str:
        role = self.setting("role", "")
        return role if role in ROLES else ""

    def token(self) -> str:
        if self._token is None:
            self._token = load_secret(SECRET_SERVICE, SECRET_NAME, fallback_dir=self.home, keyring_module=self._keyring) or ""
        return self._token

    def table_ids(self) -> dict[str, str]:
        return dict(self.setting("table_ids", {}) or {})

    def client(self) -> TeableClient:
        url, token = str(self.setting("teable_url", "") or ""), self.token()
        if not url or not token:
            raise ApiError(409, "not_configured", "Teable address or token is not set")
        with self._lock:
            if self._client is None or self._client_key != (url, token):
                if self._client is not None:
                    self._client.close()
                self._client = self._client_factory(url, token)
                self._client_key = (url, token)
            return self._client

    def committer(self) -> commit_mod.Committer:
        if not self.table_ids():
            raise ApiError(409, "no_project", "no project is open: create or open a base first")
        return commit_mod.Committer(self.client(), self.store, self.schema, self.table_ids())

    # ---- connection state ---------------------------------------------------

    def connection(self, force: bool = False) -> dict[str, Any]:
        """Teable state for the status bar. Cached for a few seconds so polling stays cheap."""
        with self._lock:
            if not force and self._conn and time.monotonic() - self._conn_at < 5:
                return self._conn
        url, token = str(self.setting("teable_url", "") or ""), self.token()
        if not url or not token:
            state = {"state": "unconfigured", "message": ""}
        else:
            try:
                probe = self._client_factory(url, token, retries=0, timeout=3.0)
            except TypeError:  # factory without the keyword arguments
                probe = self._client_factory(url, token)
            try:
                probe.ping()
                state = {"state": "online", "message": ""}
            except TeableConnectionError as exc:
                state = {"state": "offline", "message": exc.message}
            except TeableError as exc:
                state = {"state": "auth" if exc.status in (401, 403) else "error", "message": str(exc)}
            finally:
                probe.close()
        with self._lock:
            self._conn, self._conn_at = state, time.monotonic()
        return state

    # ---- data access --------------------------------------------------------

    def cache_age_seconds(self) -> float | None:
        age = self.store.oldest_cache_age()
        return None if age is None else age.total_seconds()

    def tables_for_rules(self) -> dict[str, list[dict[str, Any]]]:
        """Cached rows with the user's own drafts overlaid. Rows keep ``_draft`` (draft id)."""
        drafts = self.store.list_drafts()
        out: dict[str, list[dict[str, Any]]] = {}
        for table in rules.TABLES:
            id_name = self.id_names.get(table, "")
            rows = [flatten(r) for r in self.store.cache_records(table)]
            by_key = {_s(r.get(id_name)): r for r in rows}
            for draft in (d for d in drafts if d.table == table):
                if draft.is_new:
                    row = dict(draft.fields)
                    row["_draft"] = draft.id
                    row["_draft_op"] = "create"
                    rows.append(row)
                elif draft.key in by_key:
                    by_key[draft.key]["_base"] = {k: v for k, v in by_key[draft.key].items() if not k.startswith("_")}
                    by_key[draft.key].update(draft.fields)
                    by_key[draft.key]["_draft"] = draft.id
                    by_key[draft.key]["_draft_op"] = "update"
            out[table] = rows
        return out

    def analysis(self, node: str | None = None) -> rules.Analysis:
        key = (self._rev, node or "", self.user, self._today(), self.store.count_drafts())
        with self._lock:
            found = self._analysis_cache.get(key)
        if found is None:
            ctx = rules.Context(today=self._today(), user=self.user, node=node or None,
                                drafts=self.store.count_drafts())
            found = rules.analyse(self.tables_for_rules(), ctx)
            with self._lock:
                self._analysis_cache[key] = found
        return found

    def known_ids(self) -> dict[str, set[str]]:
        return validation.known_ids_from(self.schema, self.store)

    # ---- state / meta -------------------------------------------------------

    def meta(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        return {
            "schema": {"tables": self.schema["tables"], "exchange_rates": self.schema.get("exchange_rates", {})},
            "labels": self.labels,
            "screens": list(SCREENS),
            "roles": list(ROLES),
            "role_tree": ROLE_TREE,
            "role_screen": ROLE_SCREEN,
            "tree_names": list(decision_tree.TREE_NAMES),
            "modifier": platform.shortcut_modifier(),
            "list_columns": MAX_LIST_COLUMNS,
            "values": {"arch_chosen": rules.V.ARCH_CHOSEN, "yes": rules.V.YES, "no": GATE_OFF},
        }

    def state(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        conn = self.connection(force=query.get("force") == "1")
        age = self.cache_age_seconds()
        settings = self.analysis().settings
        project = settings.get("ten_du_an") or self.setting("project", "")
        return {
            "user": self.user,
            "role": self.role,
            "teable_url": self.setting("teable_url", ""),
            "has_token": bool(self.token()),
            "project": project,
            "base_id": self.setting("base_id", ""),
            "has_project": bool(self.table_ids()),
            "connection": conn,
            "drafts": self.store.count_drafts(),
            "cache_age_seconds": age,
            "can_commit": conn["state"] == "online" and bool(self.table_ids()),
            "progress": dict(self.progress),
            "default_screen": ROLE_SCREEN.get(self.role, "khoi_tao") if self.user and self.role else "khoi_tao",
            "tree": ROLE_TREE.get(self.role, "system_design"),
        }

    # ---- settings, connection test, bootstrap, refresh ---------------------

    def save_settings(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        role = _s(body.get("role"))
        if role and role not in ROLES:
            raise ApiError(422, "bad_role", f"role must be one of {', '.join(ROLES)}")
        if "user" in body:
            self.store.set_setting("user", _s(body["user"]))
        if role:
            self.store.set_setting("role", role)
        if "teable_url" in body:
            self.store.set_setting("teable_url", _s(body["teable_url"]).rstrip("/"))
        token = _s(body.get("token"))
        if token:
            save_secret(SECRET_SERVICE, SECRET_NAME, token, fallback_dir=self.home, keyring_module=self._keyring)
            self._token = token
        with self._lock:
            self._conn = None
        self._bump()
        return self.state({}, None)

    def test_connection(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        url = _s(body.get("teable_url")) or str(self.setting("teable_url", "") or "")
        token = _s(body.get("token")) or self.token()
        if not url or not token:
            raise ApiError(422, "not_configured", "Teable address and token are both needed")
        client = self._client_factory(url.rstrip("/"), token)
        try:
            info = client.ping()
        except TeableError as exc:
            raise ApiError(502, "teable_failed", str(exc)) from exc
        finally:
            client.close()
        return {"ok": True, "info": info if isinstance(info, dict) else {}}

    def bootstrap(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        base_id, name, space = _s(body.get("base_id")), _s(body.get("project_name")), _s(body.get("space_id"))
        if not (base_id or name):
            raise ApiError(422, "need_base_or_name", "give a base ID or a project name")
        settings: dict[str, Any] = {}
        lines: list[str] = []
        try:
            report = run_bootstrap(
                self.client(), base_id=base_id or None, project_name=name or None,
                space_id=space or None, schema=self.schema, settings=settings, progress=lines.append,
            )
        except BootstrapError as exc:
            raise ApiError(502, "bootstrap_failed", str(exc)) from exc
        except TeableError as exc:
            raise ApiError(502, "teable_failed", str(exc)) from exc
        self.store.set_setting("base_id", settings["base_id"])
        self.store.set_setting("table_ids", settings["table_ids"])
        if name:
            self.store.set_setting("project", name)
        self._bump()
        self.refresh({}, None)
        return {"base_id": settings["base_id"], "table_ids": settings["table_ids"], "log": lines,
                "created_tables": report.created_tables, "mismatches": [str(m) for m in report.mismatches]}

    def open_base(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        """Open an existing, already bootstrapped base: the bootstrap is safe to repeat."""
        return self.bootstrap(query, body)

    def refresh(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        committer = self.committer()

        def progress(table: str, count: int) -> None:
            self.progress = {"table": table, "count": count}

        try:
            committer.refresh_cache(progress)
        except TeableConnectionError as exc:
            raise ApiError(503, "offline", exc.message) from exc
        except TeableError as exc:
            raise ApiError(502, "teable_failed", str(exc)) from exc
        finally:
            self.progress = {}
        self._bump()
        return {"ok": True, "age": self.cache_age_seconds()}

    # ---- tables -------------------------------------------------------------

    def node_of(self, table: str, row: dict[str, Any], a: rules.Analysis) -> str:
        if _s(row.get("ma_nut")):
            return _s(row["ma_nut"])
        if _s(row.get("ma_uv")) in a.cands:
            return _s(a.cands[_s(row["ma_uv"])].get("ma_nut"))
        if table == "doi_chieu":
            uv, _ = a._check_pair(row)
            return _s(a.cands.get(uv, {}).get("ma_nut"))
        return ""

    def owner_for(self, table: str, row: dict[str, Any], node: str, a: rules.Analysis) -> str:
        return _s(row.get("phu_trach")) or _s(row.get("nguoi_nhan")) or _s(a.owner_of(node))

    def extras(self, table: str, row: dict[str, Any], a: rules.Analysis) -> dict[str, Any]:
        """Computed columns shown next to stored ones (never stored in Teable)."""
        if table == "yeu_cau":
            code = _s(row.get("ma_yc"))
            return {"n_nodes": len({_s(p.get("ma_nut")) for p in a.t["phan_bo"] if _s(p.get("ma_yc")) == code})}
        if table == "nut":
            code = _s(row.get("ma_nut"))
            out: dict[str, Any] = {"level": a.level(code), "cost": round(a.node_cost(code), 3)}
            out["next_action"] = a.next_action(code).text if a.is_leaf(code) else a.progress_text(code)
            return out
        if table == "ung_vien":
            uv = _s(row.get("ma_uv"))
            price = a.price_used(uv)
            return {"result": a.result_text(uv), "price_mvnd": None if price is None else round(price, 4)}
        if table == "mua_hang":
            deadline = a.order_by(_s(row.get("ma_uv")))
            return {"order_by": deadline.isoformat() if deadline else ""}
        return {}

    def rows(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        table = self.require_table(query.get("table", ""))
        node, owner = query.get("node", ""), query.get("owner", "")
        a = self.analysis()
        id_name = self.id_names[table]
        out: list[dict[str, Any]] = []
        for row in a.t[table]:
            row_node = self.node_of(table, row, a)
            if node and not (row_node == node or row_node.startswith(node + ".") or
                             (table == "nut" and _s(row.get("ma_cha")) == node)):
                continue
            if owner and self.owner_for(table, row, row_node, a) != owner:
                continue
            key = _s(row.get(id_name))
            fields = {k: v for k, v in row.items() if not k.startswith("_")}
            out.append({
                "key": key,
                "fields": fields,
                "draft": row.get("_draft"),
                "draft_op": row.get("_draft_op"),
                "base": row.get("_base") or fields,
                "record_id": row.get("_record_id"),
                "modified": row.get("_modified"),
                "node": row_node,
                "owner": self.owner_for(table, row, row_node, a),
                "warnings": [w.text for w in a.warnings_for(table, key)],
                "extras": self.extras(table, row, a),
            })
        out.sort(key=lambda r: natural_key(r["key"]))
        return {
            "table": table, "id_field": id_name, "rows": out,
            "age": self.cache_age_seconds(),
            "names": self.names(a),
            "owners": sorted({_s(r.get("phu_trach")) for r in a.t["nut"] if _s(r.get("phu_trach"))}),
            "nodes": sorted(a.nodes, key=natural_key),
        }

    def names(self, a: rules.Analysis) -> dict[str, dict[str, str]]:
        """code -> short name for every table a code can point at, so the UI shows "N1 - Propulsion"."""
        def build(table: str, label: Callable[[dict[str, Any]], str]) -> dict[str, str]:
            id_name = self.id_names[table]
            return {_s(r.get(id_name)): label(r)[:60] for r in a.t[table] if _s(r.get(id_name))}

        return {
            "nut": build("nut", lambda r: _s(r.get("ten"))),
            "yeu_cau": build("yeu_cau", lambda r: _s(r.get("mo_ta"))),
            "kien_truc": build("kien_truc", lambda r: _s(r.get("ten"))),
            "thong_so": build("thong_so", lambda r: _s(r.get("thong_so"))),
            "ung_vien": build("ung_vien", lambda r: f"{_s(r.get('hang'))} {_s(r.get('model'))}".strip()),
            "moc": build("moc", lambda r: _s(r.get("ten"))),
        }

    def require_table(self, table: str) -> str:
        if table not in self.id_names:
            raise ApiError(404, "unknown_table", f"no table {table!r}")
        return table

    def csv_export(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        """CSV text of a table view (same filters as rows), with a BOM so Excel reads UTF-8."""
        data = self.rows(query, None)
        table = data["table"]
        columns = list(schema_mod.fields_of(self.schema, table))
        extra_names = sorted({k for r in data["rows"] for k in r["extras"]})
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns + extra_names + ["draft"])
        for row in data["rows"]:
            writer.writerow(
                [row["fields"].get(c, "") for c in columns] + [row["extras"].get(c, "") for c in extra_names]
                + ["1" if row["draft"] else ""]
            )
        return {"filename": f"{table}.csv", "text": "﻿" + buffer.getvalue()}

    def next_id(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        table = self.require_table(query.get("table", ""))
        existing = self.known_ids().get(table, set())
        prefix, parent = query.get("prefix") or None, query.get("parent") or None
        try:
            proposed = schema_mod.next_free_id(self.schema, table, existing, prefix=prefix, parent=parent)
        except ValueError as exc:
            raise ApiError(422, "no_proposal", str(exc)) from exc
        return {"id": proposed}

    # ---- drafts -------------------------------------------------------------

    def check_role_for(self, table: str, key: str, fields: dict[str, Any]) -> None:
        """Gates and the chosen architecture are for the System designer only (section 2)."""
        restricted = (
            (table == "cai_dat" and (key in GATE_KEYS + (REVIEW_KEY,)
                                     or _s(fields.get("khoa")) in GATE_KEYS + (REVIEW_KEY,)))
            or (table == "kien_truc" and fields.get("trang_thai") == rules.V.ARCH_CHOSEN)
        )
        if restricted and self.role != SYSTEM_DESIGNER:
            raise ApiError(
                403, "role_required", f"{table} {key}: only the System designer may do this",
                table=table, key=key,
            )
        retiring = table == "sai_lech" and fields.get("trang_thai") == rules.V.CANCELLED
        if retiring and self.role not in CHANGE_CARD_RETIRE_ROLES:
            raise ApiError(
                403, "role_required", f"{table} {key}: only the System designer or the PM may cancel a finding",
                table=table, key=key,
            )

    def issues_payload(self, issues: list[validation.Issue]) -> list[dict[str, str]]:
        return [dataclasses.asdict(i) for i in issues]

    def save_draft(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        table = self.require_table(_s(body.get("table")))
        id_name = self.id_names[table]
        draft_id = body.get("draft_id")
        op = _s(body.get("op")) or "create"
        existing = self.store.get_draft(int(draft_id)) if draft_id else None
        if existing is not None:
            op, table = existing.op, existing.table
        raw_fields = dict(body.get("fields") or {})
        if op == "update":  # an emptied field is sent as null so the change clears it
            fields = {k: (None if v == "" else v) for k, v in raw_fields.items()}
        else:
            fields = {k: v for k, v in raw_fields.items() if v is not None and v != ""}
        key = _s(body.get("key")) or _s(fields.get(id_name)) or (existing.key if existing else "")
        self.check_role_for(table, key, fields)

        if existing is not None and existing.op == "create" and _s(body.get("op")) == "update":
            # a partial change (e.g. choosing an architecture) to a not-yet-committed new record
            merged = {**existing.fields, **{k: v for k, v in fields.items() if k != id_name}}
        elif op == "create":
            merged = fields
        else:
            merged = {k: v for k, v in fields.items() if k != id_name}
            if existing is None:
                other = next((d for d in self.store.list_drafts(table) if d.op == "update" and d.key == key), None)
                if other is not None:
                    existing = other
                    merged = {**other.fields, **merged}
        known = self.known_ids()
        if op == "create":
            clash = [d for d in self.store.list_drafts(table) if d.key == key and (existing is None or d.id != existing.id)]
            if clash:
                raise ApiError(409, "duplicate_draft", f"{key} is already in your drafts", key=key)
        issues = validation.validate_record(self.schema, table, merged, known_ids=known, op=op, key=key)
        if issues:
            raise ApiError(422, "invalid", "; ".join(i.message for i in issues), issues=self.issues_payload(issues))
        if existing is not None:
            saved = self.store.update_draft(existing.id, fields=merged, key=key)
        else:
            saved = self.store.add_draft(
                table, id_name, merged, op=op, record_id=body.get("record_id"),
                base_modified=body.get("base_modified"), base_fields=body.get("base_fields") or {},
                key=key or None,
            )
        self._bump()
        return {
            "draft": self.draft_payload(saved, known), "drafts": self.store.count_drafts(),
            "warnings": self.row_warnings(table, key, merged),
        }

    def row_warnings(self, table: str, key: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
        """Rule warnings that touch a just-saved row: its own, and those of its node (e.g. 'too early')."""
        a = self.analysis()
        node = self.node_of(table, fields, a)
        return [
            self.warning_payload(w) for w in a.warnings()
            if (w.table == table and w.key == key) or (node and w.node == node)
        ]

    @staticmethod
    def warning_payload(w: rules.Warn) -> dict[str, Any]:
        return {"code": w.code, "table": w.table, "key": w.key, "text": w.text, "node": w.node, "owner": w.owner}

    def draft_payload(self, draft: Draft, known: dict[str, set[str]] | None = None) -> dict[str, Any]:
        issues = validation.validate_draft(self.schema, draft, known or self.known_ids())
        return {
            "id": draft.id, "table": draft.table, "op": draft.op, "key": draft.key, "fields": draft.fields,
            "record_id": draft.record_id, "updated_at": draft.updated_at,
            "issues": self.issues_payload(issues), "valid": not issues,
        }

    def drafts(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        known = self.known_ids()
        return {"drafts": [self.draft_payload(d, known) for d in self.store.list_drafts()]}

    def discard_draft(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        """Remove a LOCAL draft. Nothing in Teable is touched."""
        try:
            self.store.get_draft(int(body.get("draft_id", 0)))
        except KeyError as exc:
            raise ApiError(404, "no_draft", str(exc)) from exc
        self.store.remove_draft(int(body["draft_id"]))
        self._bump()
        return {"drafts": self.store.count_drafts()}

    # ---- commit -------------------------------------------------------------

    def commit(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        for draft in self.store.list_drafts():
            self.check_role_for(draft.table, draft.key, draft.fields)
        committer = self.committer()
        try:
            report = committer.commit()
        except commit_mod.CommitDisabledError as exc:
            self.connection(force=True)
            raise ApiError(503, "commit_disabled", str(exc)) from exc
        except UniqueFlagError as exc:
            raise ApiError(409, "unique_flag_missing", str(exc), fields=exc.fields) from exc
        except TeableError as exc:
            raise ApiError(502, "teable_failed", str(exc)) from exc
        self._bump()
        if report.committed:
            try:
                committer.refresh_cache()
            except TeableError as exc:
                log.warning("refresh after commit failed: %s", exc)
            self._bump()
        return {
            "results": [dataclasses.asdict(r) for r in report.results],
            "ok": report.ok,
            "drafts": self.store.count_drafts(),
        }

    def accept_new_id(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        committer = self.committer()
        try:
            rewritten = committer.accept_new_id(int(body["draft_id"]), _s(body.get("new_id")))
        except (ValueError, KeyError) as exc:
            raise ApiError(422, "bad_new_id", str(exc)) from exc
        self._bump()
        return {"rewritten": rewritten}

    def resolve_stale(self, query: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        committer = self.committer()
        try:
            kept = committer.resolve_stale(int(body["draft_id"]), dict(body.get("choices") or {}))
        except (ValueError, KeyError) as exc:
            raise ApiError(422, "bad_choice", str(exc)) from exc
        except TeableError as exc:
            raise ApiError(502, "teable_failed", str(exc)) from exc
        self._bump()
        return {"remaining": kept is not None}

    # ---- decision tree ------------------------------------------------------

    def trees_payload(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        node = query.get("node") or None
        a = self.analysis(node)
        out: dict[str, Any] = {}
        for name, questions in self.tree_store.trees.items():
            result = decision_tree.evaluate(questions, a)
            if name == "designer" and not node:
                result = decision_tree.TreeResult(False)  # no node chosen: a plain reference
            out[name] = {
                "questions": [self.question_payload(q) for q in questions],
                "highlighted": result.highlighted,
                "steps": [dataclasses.asdict(s) for s in result.steps],
                "leaf": dataclasses.asdict(result.leaf) if result.leaf else None,
            }
        return {"trees": out, "guide": self.tree_store.guide, "node": node or "", "first": ROLE_TREE.get(self.role, "system_design")}

    @staticmethod
    def question_payload(q: decision_tree.Question) -> dict[str, Any]:
        def branch(b: decision_tree.Branch | None) -> dict[str, Any] | None:
            return None if b is None else {"do": b.do, "screen": b.screen}

        return {"index": q.index, "q": q.q, "check": q.check, "yes": branch(q.yes), "no": branch(q.no), "help": q.help}

    def reload_trees(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        try:
            self.tree_store.reload()
        except decision_tree.DecisionTreeError as exc:
            raise ApiError(422, "tree_file_bad", str(exc)) from exc
        self._bump()
        return {"ok": True}

    # ---- screens ------------------------------------------------------------

    def overview(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        a = self.analysis()
        me = self.user
        leaves = [
            {"code": c, "name": _s(a.nodes[c].get("ten")), "next": a.next_action(c).text, "row": a.next_action(c).row}
            for c in sorted(a.leaves, key=natural_key) if me and a.owner_of(c) == me
        ]
        warnings = [
            {"table": w.table, "key": w.key, "text": w.text, "node": w.node, "owner": w.owner}
            for w in a.warnings() if me and w.owner == me
        ]
        tasks = [
            {"key": _s(t.get("ma_cv")), "title": _s(t.get("tieu_de")), "node": _s(t.get("ma_nut")),
             "due": _s(t.get("han"))}
            for t in a.t["cong_viec"] if me and _s(t.get("nguoi_nhan")) == me and _s(t.get("trang_thai")) in ("", "Mở")
        ]
        return {
            "leaves": leaves,
            "counters": [{"name": n, "text": t, "value": v} for n, t, v in a.counters_labeled()],
            "warnings": warnings,
            "tasks": tasks,
            "my_findings": [f for f in self.open_findings(a) if me and f["owner"] == me],
            "total_warnings": len(a.warnings()),
        }

    # ---- weekly review (docs/designs/review-first-pilot.md) -----------------------

    @staticmethod
    def open_findings(a: rules.Analysis) -> list[dict[str, Any]]:
        """Open change cards (review findings are change cards), oldest ID first."""
        cards = [
            {"key": _s(r.get("ma_sl")), "text": _s(r.get("mo_ta")), "node": _s(r.get("ma_nut")),
             "owner": _s(r.get("nguoi_nhan")), "due": _s(r.get("han"))}
            for r in a.t["sai_lech"] if _s(r.get("trang_thai")) in ("", rules.V.CHANGE_OPEN)
        ]
        return sorted(cards, key=lambda c: natural_key(c["key"]))

    def review_cycle_days(self, a: rules.Analysis) -> int:
        value = rules._num(a.settings.get(REVIEW_CYCLE_KEY))
        return int(value) if value and value > 0 else REVIEW_CYCLE_DEFAULT

    def review_since(self, a: rules.Analysis) -> str:
        """The last review's end (Teable's clock), or one cycle back from today before the first review."""
        last = _s(a.settings.get(REVIEW_KEY))
        if last:
            return last
        return (self._today() - timedelta(days=self.review_cycle_days(a))).isoformat()

    def committed_rows(self, a: rules.Analysis) -> list[tuple[str, dict[str, Any]]]:
        """Rows that exist in Teable (they carry its lastModifiedTime), in review order."""
        return [
            (table, row) for table in rules.TABLES if table not in REVIEW_SKIP_TABLES
            for row in a.t[table] if _s(row.get("_modified"))
        ]

    def review(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        """The weekly review: per owner, then per leaf; plus the system group (rows with no owner)."""
        a = self.analysis()
        since = self.review_since(a)
        groups: dict[str, dict[str, Any]] = {"": self.review_group("")}
        for code in sorted(a.leaves, key=natural_key):
            owner = a.owner_of(code) or ""
            groups.setdefault(owner, self.review_group(owner))["leaves"].append(
                {"code": code, "name": _s(a.nodes[code].get("ten")), "next": a.next_action(code).text,
                 "row": a.next_action(code).row})
        for w in a.warnings():
            groups.setdefault(w.owner or "", self.review_group(w.owner or ""))["warnings"].append(
                self.warning_payload(w))
        id_names = self.id_names
        for table, row in self.committed_rows(a):
            if _s(row.get("_modified")) <= since:
                continue
            owner = self.owner_for(table, row, self.node_of(table, row, a), a)
            groups.setdefault(owner, self.review_group(owner))["changed"].append(
                {"table": table, "key": _s(row.get(id_names.get(table, ""))),
                 "node": self.node_of(table, row, a), "modified": _s(row.get("_modified"))})
        ordered = [groups[""]] + [groups[o] for o in sorted(groups) if o]
        return {
            "groups": ordered,
            "counters": [{"name": n, "text": t, "value": v} for n, t, v in a.counters_labeled()],
            "findings": self.open_findings(a),
            "since": since,
            "cycle_days": self.review_cycle_days(a),
        }

    @staticmethod
    def review_group(owner: str) -> dict[str, Any]:
        return {"owner": owner, "leaves": [], "warnings": [], "changed": []}

    def end_review(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        """Close the review: refresh, then stamp the newest change seen (Teable's clock, never the laptop's)."""
        if self.role != SYSTEM_DESIGNER:
            raise ApiError(403, "role_required", "only the System designer may end a review")
        self.refresh(query, body)  # offline raises 503 here, so no draft is made
        a = self.analysis()
        newest = max((_s(r.get("_modified")) for _, r in self.committed_rows(a)), default="")
        if not newest:
            raise ApiError(409, "nothing_to_review", "no committed rows in the cache; refresh and try again")
        existing = next((r for r in a.t["cai_dat"] if _s(r.get("khoa")) == REVIEW_KEY), None)
        pending = next((d for d in self.store.list_drafts("cai_dat") if d.key == REVIEW_KEY), None)
        if existing is not None and existing.get("_record_id"):
            request: dict[str, Any] = {
                "table": "cai_dat", "op": "update", "key": REVIEW_KEY, "record_id": existing["_record_id"],
                "base_modified": existing.get("_modified"), "base_fields": {"gia_tri": _s(existing.get("gia_tri"))},
                "fields": {"gia_tri": newest},
            }
        else:
            request = {"table": "cai_dat", "op": "create", "fields": {"khoa": REVIEW_KEY, "gia_tri": newest}}
        if pending is not None:
            request["draft_id"] = pending.id
        return self.save_draft({}, request)

    def architectures(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        a = self.analysis()
        weights = [rules._num(a.settings.get(k)) or 0.0 for k in WEIGHT_KEYS]
        if not any(w > 0 for w in weights):
            weights = [1.0, 1.0, 1.0]  # no weights set yet: score the three criteria equally
        cards = []
        for row in sorted(a.t["kien_truc"], key=lambda r: _s(r.get("ma_kt"))):
            scores = [rules._num(row.get(f)) for f in SCORE_FIELDS]
            used = [(s, w) for s, w in zip(scores, weights) if s is not None and w > 0]
            total = (sum(s * w for s, w in used) / sum(w for _, w in used)) if used else None
            code = _s(row.get("ma_kt"))
            cards.append({
                "key": code, "fields": {k: v for k, v in row.items() if not k.startswith("_")},
                "scores": scores, "weighted": None if total is None else round(total, 2),
                "draft": row.get("_draft"), "record_id": row.get("_record_id"), "modified": row.get("_modified"),
                "warnings": [w.text for w in a.warnings_for("kien_truc", code)],
            })
        return {"cards": cards, "weights": weights, "can_choose": self.role == SYSTEM_DESIGNER}

    def tree_nodes(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        a = self.analysis()
        roots = sorted((c for c, r in a.nodes.items() if not _s(r.get("ma_cha")) or _s(r["ma_cha"]) not in a.nodes),
                       key=natural_key)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        def walk(code: str, depth: int) -> None:
            if code in seen:
                return
            seen.add(code)
            row = a.nodes[code]
            leaf = a.is_leaf(code)
            out.append({
                "code": code, "parent": _s(row.get("ma_cha")), "name": _s(row.get("ten")), "level": a.level(code),
                "depth": depth, "owner": _s(row.get("phu_trach")), "leaf": leaf, "type": _s(row.get("loai")),
                "next": a.next_action(code).text if leaf else a.progress_text(code),
                "cost": round(a.node_cost(code), 3), "draft": row.get("_draft"),
                "record_id": row.get("_record_id"), "modified": row.get("_modified"),
                "warnings": [w.text for w in a.warnings_for("nut", code)],
            })
            for child in sorted(a.children.get(code, []), key=natural_key):
                walk(child, depth + 1)

        for root in roots:
            walk(root, 0)
        for code in sorted(a.nodes, key=natural_key):
            walk(code, 0)
        gates = {k: a.gate(int(k[-1])) for k in GATE_KEYS}
        return {"names": self.names(a), "nodes": out, "gates": gates, "can_gate": self.role == SYSTEM_DESIGNER}

    def alloc_matrix(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        a = self.analysis()
        columns = sorted({c for c in a.leaves} | {_s(p.get("ma_nut")) for p in a.t["phan_bo"]}, key=natural_key)
        cells: dict[str, dict[str, Any]] = {}
        for p in a.t["phan_bo"]:
            cells[f"{_s(p.get('ma_yc'))}|{_s(p.get('ma_nut'))}"] = {
                "key": _s(p.get("ma_pb")), "kieu": _s(p.get("kieu")), "value": p.get("gia_tri_phan_bo"),
                "unit": _s(p.get("don_vi")), "draft": p.get("_draft"),
            }
        budgets = {
            yc: {"total": round(b.total, 4), "limit": b.limit, "margin": None if b.margin is None else round(b.margin, 4),
                 "over": b.over, "method": b.method}
            for yc, b in a.budget_totals().items()
        }
        reqs = [{"code": _s(r.get("ma_yc")), "text": _s(r.get("mo_ta")), "muc": _s(r.get("muc"))}
                for r in sorted(a.t["yeu_cau"], key=lambda r: natural_key(_s(r.get("ma_yc"))))]
        return {"requirements": reqs, "nodes": [c for c in columns if c in a.nodes or c],
                "cells": cells, "budgets": budgets, "names": self.names(a)}

    def node_detail(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        code = query.get("code", "")
        a = self.analysis(code or None)
        if code not in a.nodes:
            return {"leaves": [{"code": c, "name": _s(a.nodes[c].get("ten")), "owner": a.owner_of(c) or ""}
                               for c in sorted(a.leaves, key=natural_key)], "node": None}
        node = a.nodes[code]

        def clean(row: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in row.items() if not k.startswith("_")}

        specs = sorted(a.specs_by_node.get(code, []), key=lambda r: natural_key(_s(r.get("ma_ts"))))
        cands = sorted(a.cands_by_node.get(code, []), key=lambda r: natural_key(_s(r.get("ma_uv"))))
        shown = [c for c in cands if _s(c.get("trang_thai")) != rules.V.CAND_REJECTED][:5]
        matrix = []
        for spec in specs:
            ts = _s(spec.get("ma_ts"))
            cells = []
            for cand in shown:
                uv = _s(cand.get("ma_uv"))
                row = a.checks.get((uv, ts), {})
                cells.append({
                    "uv": uv, "state": a.check_state(uv, ts), "value": row.get("gia_tri_so"),
                    "quote": _s(row.get("trich_dan")), "page": _s(row.get("trang")),
                    "hand": _s(row.get("danh_gia_tay")), "draft": row.get("_draft"),
                })
            matrix.append({"ts": ts, "name": _s(spec.get("thong_so")), "muc": _s(spec.get("muc")),
                           "min": spec.get("gia_tri_min"), "max": spec.get("gia_tri_max"),
                           "unit": _s(spec.get("don_vi")), "cells": cells})
        return {
            "node": {**clean(node), "leaf": a.is_leaf(code), "level": a.level(code),
                     "next": a.next_action(code).text if a.is_leaf(code) else a.progress_text(code),
                     "step": a.next_action(code).step if a.is_leaf(code) else None},
            "allocations": [clean(p) | {"_key": _s(p.get("ma_pb")), "_draft": p.get("_draft")}
                            for p in a.alloc_by_node.get(code, [])],
            "specs": [clean(s) | {"_draft": s.get("_draft"), "_warnings": [w.text for w in a.warnings_for("thong_so", _s(s.get("ma_ts")))]}
                      for s in specs],
            "candidates": [clean(c) | {"_draft": c.get("_draft"), "_result": a.result_text(_s(c.get("ma_uv"))),
                                       "_warnings": [w.text for w in a.warnings_for("ung_vien", _s(c.get("ma_uv")))]}
                           for c in cands],
            "compare": {"candidates": [_s(c.get("ma_uv")) for c in shown],
                        "results": {_s(c.get("ma_uv")): a.result_text(_s(c.get("ma_uv"))) for c in shown},
                        "pass": {_s(c.get("ma_uv")): a.candidate_result(_s(c.get("ma_uv"))) == rules.RES_PASS for c in shown},
                        "rows": matrix},
            "leaves": [],
            "names": self.names(a),
        }

    def sourcing(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        a = self.analysis()
        queue = []
        for uv in a.sourcing_queue():
            c = a.cands[uv]
            queue.append({"uv": uv, "node": _s(c.get("ma_nut")), "hang": _s(c.get("hang")), "model": _s(c.get("model")),
                          "price": c.get("gia_cong_bo"), "currency": _s(c.get("tien_te")),
                          "owner": _s(a.owner_of(_s(c.get("ma_nut"))))})
        return {"queue": queue, "names": self.names(a)}

    # ---- routing ------------------------------------------------------------

    def _build_routes(self) -> dict[tuple[str, str], Callable[[dict[str, str], Any], Any]]:
        return {
            ("GET", "/api/meta"): self.meta,
            ("GET", "/api/state"): self.state,
            ("POST", "/api/settings"): self.save_settings,
            ("POST", "/api/connection/test"): self.test_connection,
            ("POST", "/api/bootstrap"): self.bootstrap,
            ("POST", "/api/base/open"): self.open_base,
            ("POST", "/api/refresh"): self.refresh,
            ("GET", "/api/rows"): self.rows,
            ("GET", "/api/csv"): self.csv_export,
            ("GET", "/api/next_id"): self.next_id,
            ("POST", "/api/draft"): self.save_draft,
            ("GET", "/api/drafts"): self.drafts,
            ("POST", "/api/draft/discard"): self.discard_draft,
            ("POST", "/api/commit"): self.commit,
            ("POST", "/api/commit/accept"): self.accept_new_id,
            ("POST", "/api/commit/stale"): self.resolve_stale,
            ("GET", "/api/trees"): self.trees_payload,
            ("POST", "/api/trees/reload"): self.reload_trees,
            ("GET", "/api/overview"): self.overview,
            ("GET", "/api/review"): self.review,
            ("POST", "/api/review/end"): self.end_review,
            ("GET", "/api/architectures"): self.architectures,
            ("GET", "/api/tree_nodes"): self.tree_nodes,
            ("GET", "/api/alloc"): self.alloc_matrix,
            ("GET", "/api/node"): self.node_detail,
            ("GET", "/api/sourcing"): self.sourcing,
        }

    def dispatch(self, method: str, path: str, query: dict[str, str], body: Any) -> tuple[int, Any]:
        """Run one API call. Returns (status, JSON-able payload); never raises."""
        handler = self.routes.get((method, path))
        if handler is None:
            return 404, ApiError(404, "no_route", f"{method} {path}").payload()
        try:
            return 200, handler(query, body)
        except ApiError as exc:
            return exc.status, exc.payload()
        except TeableConnectionError as exc:
            return 503, ApiError(503, "offline", exc.message).payload()
        except TeableError as exc:
            return 502, ApiError(502, "teable_failed", str(exc)).payload()
        except Exception as exc:  # last resort: show it, log it, never a blank screen
            log.exception("unhandled error in %s %s", method, path)
            return 500, ApiError(500, "internal", f"{type(exc).__name__}: {exc}").payload()



# ---- HTTP layer ---------------------------------------------------------------


def make_handler(app: App, port_holder: list[int]) -> type[BaseHTTPRequestHandler]:
    """Request handler class bound to ``app``. ``port_holder[0]`` is filled once the port is known."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "T3Desk"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # route access log to the rotating log, no tokens in URLs
            log.debug("http %s", fmt % args)

        # -- helpers
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_holder[0]}", f"localhost:{port_holder[0]}")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _handle(self, method: str) -> None:
            if not self._host_ok():
                self._json(403, ApiError(403, "bad_host", "only 127.0.0.1 is served").payload())
                return
            url = urlparse(self.path)
            if method == "GET" and not url.path.startswith("/api/"):
                self._static(url.path)
                return
            if not url.path.startswith("/api/"):
                self._json(404, ApiError(404, "no_route", url.path).payload())
                return
            if not secrets.compare_digest(self.headers.get(SESSION_HEADER) or "", app.session):
                self._json(403, ApiError(403, "bad_session", "missing or wrong session header").payload())
                return
            body: Any = None
            if method == "POST":
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    self._json(415, ApiError(415, "bad_content_type", "POST needs application/json").payload())
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self._json(413, ApiError(413, "too_large", f"body over {MAX_BODY} bytes").payload())
                    return
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError) as exc:
                    self._json(400, ApiError(400, "bad_json", str(exc)).payload())
                    return
            query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            status, payload = app.dispatch(method, url.path, query, body)
            self._json(status, payload)

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            content_type = STATIC_TYPES.get(name)
            target = UI_DIR / name
            if content_type is None or not target.is_file():
                self._json(404, ApiError(404, "no_file", name).payload())
                return
            data = target.read_bytes()
            if name == "index.html":
                data = data.replace(SESSION_PLACEHOLDER.encode(), app.session.encode())
            self._send(200, data, content_type)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

    return Handler


class RunningServer:
    """The HTTP server on a background thread."""

    def __init__(self, app: App, host: str = "127.0.0.1", port: int = 0):
        holder: list[int] = [0]
        self.app = app
        self.httpd = ThreadingHTTPServer((host, port), make_handler(app, holder))
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        holder[0] = self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="t3desk-http", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> RunningServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def make_server(app: App, port: int = 0) -> RunningServer:
    return RunningServer(app, port=port)


def setup_logging(home: Path) -> None:
    """One rotating log file per user in the config folder."""
    handler = logging.handlers.RotatingFileHandler(home / "t3desk.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("t3desk")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
