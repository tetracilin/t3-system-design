"""Local storage: one SQLite file per user for drafts, the Teable cache and settings.

Tokens never go into the SQLite file. They live in the OS keyring, or, when no keyring
backend exists, in a file that only the user can read (see ``save_secret``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

log = logging.getLogger("t3desk.store")

Clock = Callable[[], datetime]
FORBIDDEN_SETTING = re.compile(r"token|secret|password|passwd", re.IGNORECASE)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name    TEXT NOT NULL,
    op            TEXT NOT NULL CHECK (op IN ('create', 'update')),
    key           TEXT NOT NULL,
    record_id     TEXT,
    fields        TEXT NOT NULL,
    base_modified TEXT,
    base_fields   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
    table_name TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    record     TEXT NOT NULL,
    PRIMARY KEY (table_name, record_id)
);
CREATE TABLE IF NOT EXISTS cache_meta (
    table_name TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
# drafts.key           value of the record's ID field
# drafts.record_id     Teable record id (updates only)
# drafts.fields        JSON, what the user typed
# drafts.base_modified lastModifiedTime the edit was based on (updates only)
# drafts.base_fields   JSON, the record as it was when loaded (updates only)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Draft:
    id: int
    table: str
    op: str
    key: str
    fields: dict[str, Any]
    record_id: str | None = None
    base_modified: str | None = None
    base_fields: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_new(self) -> bool:
        return self.op == "create"


class Store:
    """SQLite-backed drafts, cache and settings. Safe to share between threads."""

    def __init__(self, path: str | Path, *, clock: Clock = utc_now):
        self.path = str(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA_SQL)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- settings -----------------------------------------------------------

    def set_setting(self, key: str, value: Any) -> None:
        if FORBIDDEN_SETTING.search(key):
            raise ValueError(f"setting {key!r} looks like a secret; use save_secret instead")
        with self._lock:
            self._db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._db.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def all_settings(self) -> dict[str, Any]:
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    # ---- drafts -------------------------------------------------------------

    def add_draft(
        self,
        table: str,
        id_field: str,
        fields: dict[str, Any],
        *,
        op: str = "create",
        record_id: str | None = None,
        base_modified: str | None = None,
        base_fields: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> Draft:
        """Save a draft. For a create, the key is ``fields[id_field]``; for an update the
        caller passes ``key`` (the record's ID) because the ID is not part of the changes."""
        draft_key = key if key is not None else str(fields.get(id_field, ""))
        if not draft_key:
            raise ValueError(f"draft for {table} has no {id_field}")
        if op == "update" and not record_id:
            raise ValueError("an update draft needs the Teable record id")
        now = _iso(self._clock())
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO drafts(table_name, op, key, record_id, fields, base_modified, base_fields,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (table, op, draft_key, record_id, json.dumps(fields, ensure_ascii=False), base_modified,
                 json.dumps(base_fields or {}, ensure_ascii=False), now, now),
            )
            self._db.commit()
            return self.get_draft(int(cur.lastrowid))

    def update_draft(
        self,
        draft_id: int,
        *,
        fields: dict[str, Any] | None = None,
        key: str | None = None,
        base_modified: str | None = None,
        base_fields: dict[str, Any] | None = None,
    ) -> Draft:
        current = self.get_draft(draft_id)
        new_fields = current.fields if fields is None else fields
        with self._lock:
            self._db.execute(
                "UPDATE drafts SET fields = ?, key = ?, base_modified = ?, base_fields = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    json.dumps(new_fields, ensure_ascii=False),
                    current.key if key is None else key,
                    current.base_modified if base_modified is None else base_modified,
                    json.dumps(current.base_fields if base_fields is None else base_fields, ensure_ascii=False),
                    _iso(self._clock()),
                    draft_id,
                ),
            )
            self._db.commit()
        return self.get_draft(draft_id)

    def get_draft(self, draft_id: int) -> Draft:
        with self._lock:
            row = self._db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(f"no draft {draft_id}")
        return _draft_from_row(row)

    def list_drafts(self, table: str | None = None) -> list[Draft]:
        sql, args = "SELECT * FROM drafts", ()
        if table is not None:
            sql, args = sql + " WHERE table_name = ?", (table,)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY id", args).fetchall()
        return [_draft_from_row(r) for r in rows]

    def count_drafts(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])

    def remove_draft(self, draft_id: int) -> None:
        """Remove a LOCAL draft (after commit or when the user discards it). Never touches Teable."""
        with self._lock:
            self._db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            self._db.commit()

    # ---- cache --------------------------------------------------------------

    def replace_cache(
        self, table: str, records: list[dict[str, Any]], *, fetched_at: datetime | None = None
    ) -> None:
        """Replace the cached copy of one table with a fresh full listing."""
        stamp = _iso(fetched_at or self._clock())
        with self._lock:
            self._db.execute("DELETE FROM cache WHERE table_name = ?", (table,))
            self._db.executemany(
                "INSERT INTO cache(table_name, record_id, record) VALUES (?, ?, ?)",
                [(table, r["id"], json.dumps(r, ensure_ascii=False)) for r in records],
            )
            self._db.execute(
                "INSERT INTO cache_meta(table_name, fetched_at) VALUES (?, ?) "
                "ON CONFLICT(table_name) DO UPDATE SET fetched_at = excluded.fetched_at",
                (table, stamp),
            )
            self._db.commit()

    def put_cached_record(self, table: str, record: dict[str, Any]) -> None:
        """Store one record (for example the answer of a create) without touching the fetch time."""
        with self._lock:
            self._db.execute(
                "INSERT INTO cache(table_name, record_id, record) VALUES (?, ?, ?) "
                "ON CONFLICT(table_name, record_id) DO UPDATE SET record = excluded.record",
                (table, record["id"], json.dumps(record, ensure_ascii=False)),
            )
            self._db.commit()

    def cache_records(self, table: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT record FROM cache WHERE table_name = ? ORDER BY rowid", (table,)
            ).fetchall()
        return [json.loads(r["record"]) for r in rows]

    def cache_record(self, table: str, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM cache WHERE table_name = ? AND record_id = ?", (table, record_id)
            ).fetchone()
        return json.loads(row["record"]) if row else None

    def cache_ids(self, table: str, id_field: str) -> set[str]:
        return {
            str(r["fields"][id_field]) for r in self.cache_records(table) if r.get("fields", {}).get(id_field)
        }

    def cache_fetched_at(self, table: str) -> datetime | None:
        with self._lock:
            row = self._db.execute(
                "SELECT fetched_at FROM cache_meta WHERE table_name = ?", (table,)
            ).fetchone()
        return datetime.fromisoformat(row["fetched_at"]) if row else None

    def cache_age(self, table: str) -> timedelta | None:
        """How old the cached copy of ``table`` is, or None if it was never fetched."""
        fetched = self.cache_fetched_at(table)
        return None if fetched is None else self._clock() - fetched

    def oldest_cache_age(self) -> timedelta | None:
        """Age of the stalest cached table (what the status bar shows when offline)."""
        with self._lock:
            rows = self._db.execute("SELECT table_name FROM cache_meta").fetchall()
        ages = [a for r in rows if (a := self.cache_age(r["table_name"])) is not None]
        return max(ages) if ages else None


def _draft_from_row(row: sqlite3.Row) -> Draft:
    return Draft(
        id=row["id"], table=row["table_name"], op=row["op"], key=row["key"],
        fields=json.loads(row["fields"]), record_id=row["record_id"],
        base_modified=row["base_modified"], base_fields=json.loads(row["base_fields"] or "{}"),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---- secrets (tokens) -------------------------------------------------------


def _load_keyring() -> ModuleType | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _usable(kr: ModuleType | None) -> bool:
    """False when the keyring package is missing or only has the 'fail' backend."""
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
    except Exception as exc:  # third-party backends raise assorted errors
        log.warning("keyring backend unavailable: %s", type(exc).__name__)
        return False
    return "fail" not in type(backend).__module__.lower()


def _secret_file(fallback_dir: Path, service: str, name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{service}__{name}")
    return Path(fallback_dir) / f"secret_{safe}.txt"


def save_secret(
    service: str, name: str, value: str, *, fallback_dir: str | Path,
    keyring_module: ModuleType | None | bool = False,
) -> str:
    """Save a token. Returns "keyring" or "file". ``keyring_module`` is for tests (None = no keyring)."""
    kr = _load_keyring() if keyring_module is False else keyring_module
    if _usable(kr):
        try:
            kr.set_password(service, name, value)
            return "keyring"
        except Exception as exc:  # fall back to the file rather than lose the token
            log.warning("keyring refused the token (%s); using the restricted file", type(exc).__name__)
    path = _secret_file(Path(fallback_dir), service, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with owner-only permissions from the start so the token is never group/world readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    os.chmod(path, 0o600)
    return "file"


def load_secret(
    service: str, name: str, *, fallback_dir: str | Path,
    keyring_module: ModuleType | None | bool = False,
) -> str | None:
    kr = _load_keyring() if keyring_module is False else keyring_module
    if _usable(kr):
        try:
            found = kr.get_password(service, name)
        except Exception as exc:
            log.warning("keyring read failed (%s); trying the restricted file", type(exc).__name__)
            found = None
        if found:
            return found
    path = _secret_file(Path(fallback_dir), service, name)
    return path.read_text(encoding="utf-8") if path.exists() else None
