"""Commit: send local drafts to Teable with first-come ID ownership.

Flow (docs/REQUIREMENTS.md section 5):
  1. check Teable answers and every ID field still has its unique flag
  2. refresh the cache
  3. order drafts so a record goes before any record that refers to it
  4. create records ONE AT A TIME (never batch), read the ID back, report per draft
  5. committed drafts are removed, everything else stays a draft

Rules kept here: nothing is deleted, an existing record created by someone else is never
changed to settle a conflict, and an update is refused when the record changed since the
draft was based on it (the caller gets both versions per field).
"""

from __future__ import annotations

import heapq
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from t3desk import schema as schema_mod
from t3desk import validation
from t3desk.store import Draft, Store
from t3desk.teable_client import (
    TeableClient,
    TeableConnectionError,
    TeableError,
    record_author,
)

log = logging.getLogger("t3desk.commit")

COMMITTED = "committed"
CONFLICT = "conflict"
FAILED = "failed"
STALE = "stale"
SKIPPED = "skipped"

# Status values that mean "retired" (data values of the schema, not UI text). Used only to
# retire OUR OWN record when the read-back shows we lost a race; nothing is ever deleted.
RETIRE_VALUES = ("Hủy", "Loại")


class CommitDisabledError(Exception):
    """Commit cannot run now (offline, bad token, ...). Drafts are untouched."""


@dataclass
class ConflictInfo:
    """An ID that someone else already holds."""

    table: str
    id_field: str
    id: str
    taken_by: str
    taken_at: str
    proposed_id: str | None


@dataclass
class StaleField:
    field: str
    base: Any  # value when the draft was started
    mine: Any  # value in the draft
    theirs: Any  # value in Teable now
    theirs_changed: bool  # someone else changed this field since the draft was based


@dataclass
class StaleInfo:
    """The record changed in Teable after the draft was based on it."""

    table: str
    key: str
    based_on: str | None
    now_modified: str
    modified_by: str
    fields: list[StaleField]


@dataclass
class DraftResult:
    draft_id: int
    table: str
    key: str
    status: str
    message: str = ""
    conflict: ConflictInfo | None = None
    stale: StaleInfo | None = None
    record: dict[str, Any] | None = None


@dataclass
class CommitReport:
    results: list[DraftResult] = field(default_factory=list)

    def by_status(self, status: str) -> list[DraftResult]:
        return [r for r in self.results if r.status == status]

    @property
    def committed(self) -> list[DraftResult]:
        return self.by_status(COMMITTED)

    @property
    def ok(self) -> bool:
        return all(r.status == COMMITTED for r in self.results)

    def lines(self) -> list[str]:
        return [f"{r.table} {r.key}: {r.status}" + (f" - {r.message}" if r.message else "") for r in self.results]


ConflictHandler = Callable[[ConflictInfo, Draft], "str | None"]
StaleHandler = Callable[[StaleInfo], "Mapping[str, str] | None"]
Progress = Callable[[str, int], None]


class Committer:
    def __init__(
        self,
        client: TeableClient,
        store: Store,
        schema: schema_mod.Schema,
        table_ids: Mapping[str, str],
        *,
        max_conflict_retries: int = 5,
    ):
        self.client = client
        self.store = store
        self.schema = schema
        self.table_ids = dict(table_ids)
        self.id_names = schema_mod.id_fields(schema)
        self.max_conflict_retries = max_conflict_retries

    # ---- preconditions ------------------------------------------------------

    def can_commit(self) -> tuple[bool, str]:
        """(True, "") when Teable answers; otherwise (False, why). Commit is disabled when False."""
        try:
            self.client.ping()
        except TeableConnectionError as exc:
            return False, f"Teable is not reachable ({exc.message}). Keep drafting; commit when it is back."
        except TeableError as exc:
            return False, f"Teable refused the connection test: {exc}"
        return True, ""

    def check_unique_flags(self) -> None:
        """Raises UniqueFlagError, naming each table.field, when an ID field lost its unique flag."""
        self.client.ensure_unique_flags(self.table_ids, {t: self.id_names[t] for t in self.table_ids})

    def refresh_cache(self, progress: Progress | None = None) -> None:
        """Re-read every table from Teable into the local cache (pages of 1000)."""
        for table, table_id in self.table_ids.items():
            done = (lambda n, t=table: progress(t, n)) if progress else None
            records = self.client.list_all_records(table_id, progress=done)
            self.store.replace_cache(table, records)

    # ---- ordering -----------------------------------------------------------

    def _dependencies(self, drafts: list[Draft]) -> dict[int, set[int]]:
        """draft id -> ids of create drafts it refers to (those must be sent first)."""
        by_key = {(d.table, d.key): d.id for d in drafts if d.is_new}
        deps: dict[int, set[int]] = {}
        for draft in drafts:
            found: set[int] = set()
            for name, spec in schema_mod.fields_of(self.schema, draft.table).items():
                ref = spec.get("ref")
                if not ref or name not in draft.fields:
                    continue
                for code in validation.split_multi(draft.fields[name], spec.get("multi")):
                    target = by_key.get((ref, code))
                    if target is not None and target != draft.id:
                        found.add(target)
            deps[draft.id] = found
        return deps

    def order_drafts(self, drafts: list[Draft]) -> list[Draft]:
        """Topological order (node before candidate before check), stable by creation order.
        If the references form a loop, the oldest draft of the loop goes first."""
        deps = self._dependencies(drafts)
        by_id = {d.id: d for d in drafts}
        waiting = {i: set(d) for i, d in deps.items()}
        dependents: dict[int, list[int]] = {i: [] for i in by_id}
        for i, needed in deps.items():
            for n in needed:
                dependents[n].append(i)
        ready = [i for i, needed in waiting.items() if not needed]
        heapq.heapify(ready)
        out: list[Draft] = []
        placed: set[int] = set()
        while len(out) < len(drafts):
            if not ready:  # loop: break it at the oldest unplaced draft
                oldest = min(i for i in by_id if i not in placed)
                waiting[oldest] = set()
                heapq.heappush(ready, oldest)
            current = heapq.heappop(ready)
            if current in placed:
                continue
            placed.add(current)
            out.append(by_id[current])
            for follower in dependents[current]:
                waiting[follower].discard(current)
                if not waiting[follower] and follower not in placed:
                    heapq.heappush(ready, follower)
        return out

    # ---- the commit ---------------------------------------------------------

    def commit(
        self,
        *,
        on_conflict: ConflictHandler | None = None,
        on_stale: StaleHandler | None = None,
        progress: Progress | None = None,
    ) -> CommitReport:
        """Send all drafts. Raises CommitDisabledError (offline) or UniqueFlagError (unsafe)."""
        ok, why = self.can_commit()
        if not ok:
            raise CommitDisabledError(why)
        self.check_unique_flags()
        try:
            self.refresh_cache(progress)
        except TeableConnectionError as exc:
            raise CommitDisabledError(f"Teable went away while refreshing: {exc.message}") from exc

        drafts = self.order_drafts(self.store.list_drafts())
        deps = self._dependencies(drafts)
        known = validation.known_ids_from(self.schema, self.store)
        report = CommitReport()
        not_sent: set[int] = set()  # drafts that did not commit; their dependents are skipped
        lost_connection = False

        for original in drafts:
            if lost_connection:
                report.results.append(self._result(original, SKIPPED, "connection to Teable was lost; draft kept"))
                continue
            blockers = deps[original.id] & not_sent
            if blockers:
                names = ", ".join(self._label(b) for b in sorted(blockers))
                report.results.append(
                    self._result(original, SKIPPED, f"waits for {names}, which was not committed")
                )
                not_sent.add(original.id)
                continue
            draft = self.store.get_draft(original.id)  # may have been rewritten by an accepted conflict
            try:
                result = self._send(draft, known, on_conflict, on_stale)
            except TeableConnectionError as exc:
                lost_connection = True
                result = self._result(draft, FAILED, f"connection lost: {exc.message}")
            report.results.append(result)
            if result.status == COMMITTED:
                self.store.remove_draft(draft.id)
            else:
                not_sent.add(draft.id)
        return report

    def _label(self, draft_id: int) -> str:
        try:
            draft = self.store.get_draft(draft_id)
        except KeyError:
            return f"draft {draft_id}"
        return f"{draft.table} {draft.key}"

    @staticmethod
    def _result(draft: Draft, status: str, message: str = "", **extra: Any) -> DraftResult:
        return DraftResult(draft.id, draft.table, draft.key, status, message, **extra)

    def _send(
        self, draft: Draft, known: dict[str, set[str]],
        on_conflict: ConflictHandler | None, on_stale: StaleHandler | None,
    ) -> DraftResult:
        issues = validation.validate_draft(self.schema, draft, known)
        if issues:
            return self._result(draft, FAILED, "; ".join(i.message for i in issues))
        if not draft.is_new:
            return self._send_update(draft, on_stale)
        for _ in range(self.max_conflict_retries + 1):
            result = self._send_create(draft)
            if result.status != CONFLICT or on_conflict is None or result.conflict is None:
                if result.status == COMMITTED:
                    known.setdefault(draft.table, set()).add(draft.key)
                return result
            new_id = on_conflict(result.conflict, draft)
            if not new_id:
                return result
            self.accept_new_id(draft.id, new_id)
            draft = self.store.get_draft(draft.id)
            known.setdefault(draft.table, set()).add(draft.key)
        return self._result(draft, CONFLICT, "gave up after repeated ID conflicts")

    # ---- create -------------------------------------------------------------

    def _send_create(self, draft: Draft) -> DraftResult:
        table_id = self.table_ids[draft.table]
        id_name = self.id_names[draft.table]
        try:
            mine = self.client.create_record(table_id, draft.fields)
        except TeableConnectionError:
            raise
        except TeableError as exc:
            if exc.is_unique_violation:
                return self._conflict(draft, None, f"the server refused the ID: {exc.message}")
            return self._result(draft, FAILED, f"{exc.message} (HTTP {exc.status}). Fix the data and commit again.")

        try:  # read the ID back: two records with the same ID means the earlier one wins
            found = self.client.find_by_field(table_id, id_name, draft.key)
        except TeableConnectionError:
            raise
        except TeableError as exc:
            log.warning("created %s %s but read-back failed: %s", draft.table, draft.key, exc)
            self.store.put_cached_record(draft.table, mine)
            return self._result(draft, COMMITTED, f"created; read-back check failed: {exc.message}", record=mine)
        # Teable's create answer has no createdTime/autoNumber; the read-back copy has them.
        mine = next((r for r in found if r["id"] == mine["id"]), mine)
        winner = min(found, key=_age_key) if found else mine
        if winner["id"] != mine["id"]:
            withdrawn = self._withdraw(draft, mine)
            note = "our duplicate was retired by status" if withdrawn else (
                "our duplicate could not be retired automatically and needs a manual status change"
            )
            return self._conflict(draft, winner, f"two records carried this ID and the earlier one wins; {note}")
        self.store.put_cached_record(draft.table, mine)
        return self._result(draft, COMMITTED, record=mine)

    def _withdraw(self, draft: Draft, mine: dict[str, Any]) -> bool:
        """Retire OUR OWN record (by status; no delete exists). Never touches another record."""
        for name, spec in schema_mod.fields_of(self.schema, draft.table).items():
            if spec["type"] == "choice":
                value = next((v for v in RETIRE_VALUES if v in spec["choices"]), None)
                if value is not None:
                    try:
                        self.client.update_record(self.table_ids[draft.table], mine["id"], {name: value})
                    except TeableError as exc:
                        log.warning("could not retire our duplicate %s: %s", mine["id"], exc)
                        return False
                    return True
        return False

    def _conflict(self, draft: Draft, winner: dict[str, Any] | None, why: str) -> DraftResult:
        table_id = self.table_ids[draft.table]
        id_name = self.id_names[draft.table]
        records = self.client.list_all_records(table_id)
        self.store.replace_cache(draft.table, records)
        if winner is None:
            holders = [r for r in records if r.get("fields", {}).get(id_name) == draft.key]
            winner = min(holders, key=_age_key) if holders else None
        existing = {str(r["fields"][id_name]) for r in records if r.get("fields", {}).get(id_name)}
        existing |= {d.key for d in self.store.list_drafts(draft.table) if d.id != draft.id}
        info = ConflictInfo(
            table=draft.table, id_field=id_name, id=draft.key,
            taken_by=record_author(winner) if winner else "",
            taken_at=(winner or {}).get("createdTime", ""),
            proposed_id=self._propose(draft, existing),
        )
        message = f"{id_name} {draft.key} is already taken by {info.taken_by or 'someone else'}"
        if info.taken_at:
            message += f" ({info.taken_at})"
        message += f"; {why}"
        if info.proposed_id:
            message += f". Next free ID: {info.proposed_id}"
        return self._result(draft, CONFLICT, message, conflict=info)

    def _propose(self, draft: Draft, existing: set[str]) -> str | None:
        spec = self.schema["tables"][draft.table]["id"]
        prefix = next((p for p in spec.get("prefixes", []) if draft.key.startswith(p)), None)
        parent = draft.key.rsplit(".", 1)[0] if "." in draft.key else None
        try:
            return schema_mod.next_free_id(self.schema, draft.table, existing, prefix=prefix, parent=parent)
        except ValueError:
            return None

    # ---- accepting a new ID -------------------------------------------------

    def accept_new_id(self, draft_id: int, new_id: str) -> int:
        """Rename a draft's ID and rewrite every local draft that refers to the old ID.

        Returns how many OTHER drafts were rewritten. Nothing is sent to Teable."""
        draft = self.store.get_draft(draft_id)
        if not draft.is_new:
            raise ValueError("only a new record can take a new ID; an ID cannot change after commit")
        id_name = self.id_names[draft.table]
        taken = self.store.cache_ids(draft.table, id_name) | {
            d.key for d in self.store.list_drafts(draft.table) if d.id != draft_id
        }
        if new_id in taken:
            raise ValueError(f"{new_id} is already used; pick another ID")
        bad = validation._check_id(self.schema, draft.table, id_name, new_id)
        if bad:
            raise ValueError(bad[0].message)

        old_id = draft.key
        fields = dict(draft.fields)
        fields[id_name] = new_id
        self.store.update_draft(draft_id, fields=fields, key=new_id)
        rewritten = 0
        for other in self.store.list_drafts():
            if other.id == draft_id:
                continue
            if self._rewrite_refs(other, draft.table, old_id, new_id):
                rewritten += 1
        return rewritten

    def _rewrite_refs(self, draft: Draft, target_table: str, old: str, new: str) -> bool:
        fields = dict(draft.fields)
        changed = False
        for name, spec in schema_mod.fields_of(self.schema, draft.table).items():
            if spec.get("ref") != target_table or name not in fields:
                continue
            sep = spec.get("multi")
            codes = validation.split_multi(fields[name], sep)
            if old in codes:
                fields[name] = (sep or "").join(new if c == old else c for c in codes)
                changed = True
        if not changed:
            return False
        key = draft.key
        id_spec = self.schema["tables"][draft.table]["id"]
        if draft.is_new and id_spec["kind"] == "composite":
            parts = id_spec["parts"]
            if all(p in fields for p in parts):  # e.g. doi_chieu key follows its ma_uv / ma_ts
                key = id_spec["separator"].join(str(fields[p]) for p in parts)
                fields[self.id_names[draft.table]] = key
        self.store.update_draft(draft.id, fields=fields, key=key)
        return True

    # ---- update of an existing record --------------------------------------

    def _send_update(self, draft: Draft, on_stale: StaleHandler | None) -> DraftResult:
        table_id = self.table_ids[draft.table]
        id_name = self.id_names[draft.table]
        try:
            current = self.client.get_record(table_id, draft.record_id or "")
        except TeableConnectionError:
            raise
        except TeableError as exc:
            return self._result(draft, FAILED, f"cannot re-read the record before sending: {exc}")
        info = self._stale_info(draft, current)
        if info is not None:
            choices = on_stale(info) if on_stale else None
            if choices is None:
                return self._result(
                    draft, STALE, f"{draft.key} was changed by {info.modified_by or 'someone else'} "
                    "after you loaded it; choose per field which version to keep", stale=info,
                )
            remaining = self.resolve_stale(draft.id, choices, current=current)
            if remaining is None:
                return self._result(draft, COMMITTED, "nothing left to send: kept the other version of every field")
            draft = remaining
        fields = {k: v for k, v in draft.fields.items() if k != id_name}
        try:
            record = self.client.update_record(table_id, draft.record_id or "", fields)
        except TeableConnectionError:
            raise
        except TeableError as exc:
            return self._result(draft, FAILED, f"{exc.message} (HTTP {exc.status}). Fix the data and commit again.")
        try:  # the update answer has no top-level lastModifiedTime; the cache needs it
            record = self.client.get_record(table_id, draft.record_id or "")
        except TeableError as exc:
            log.warning("updated %s %s but re-read failed: %s", draft.table, draft.key, exc)
        self.store.put_cached_record(draft.table, record)
        return self._result(draft, COMMITTED, record=record)

    def _stale_info(self, draft: Draft, current: dict[str, Any]) -> StaleInfo | None:
        now = current.get("lastModifiedTime", "")
        if not draft.base_modified or now == draft.base_modified:
            return None
        theirs = current.get("fields", {})
        rows = [
            StaleField(
                field=name, base=draft.base_fields.get(name), mine=mine, theirs=theirs.get(name),
                theirs_changed=theirs.get(name) != draft.base_fields.get(name),
            )
            for name, mine in draft.fields.items()
        ]
        return StaleInfo(
            table=draft.table, key=draft.key, based_on=draft.base_modified, now_modified=now,
            modified_by=record_author({"fields": {"created_by": theirs.get("last_modified_by")}}), fields=rows,
        )

    def resolve_stale(
        self, draft_id: int, choices: Mapping[str, str], *, current: dict[str, Any] | None = None
    ) -> Draft | None:
        """Apply the user's per-field choice ("mine" or "theirs"; default "mine").

        "theirs" drops the field from the draft (their value stays in Teable). The draft is
        rebased on the record as it is now. Returns None when no field is left to send."""
        draft = self.store.get_draft(draft_id)
        if current is None:
            current = self.client.get_record(self.table_ids[draft.table], draft.record_id or "")
        bad = {v for v in choices.values() if v not in ("mine", "theirs")}
        if bad:
            raise ValueError(f"choice must be 'mine' or 'theirs', got {sorted(bad)}")
        kept = {k: v for k, v in draft.fields.items() if choices.get(k, "mine") == "mine"}
        if not kept:
            self.store.remove_draft(draft_id)
            return None
        return self.store.update_draft(
            draft_id, fields=kept, base_modified=current.get("lastModifiedTime"),
            base_fields=dict(current.get("fields", {})),
        )


def _age_key(record: dict[str, Any]) -> tuple[str, int]:
    """Earlier createdTime wins; the lower autoNumber breaks a tie."""
    return str(record.get("createdTime", "")), int(record.get("autoNumber", 0) or 0)
