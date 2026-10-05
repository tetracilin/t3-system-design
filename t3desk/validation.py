"""Validation of a record before it is saved as a draft or committed.

Driven entirely by schema.yaml: ID format, required fields, allowed values, number bounds
and that every code a record refers to exists in Teable (the cache) or in the user's own
drafts. No field name appears here.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from t3desk import schema as schema_mod
from t3desk.store import Draft, Store

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

KnownIds = Mapping[str, Collection[str]]


@dataclass(frozen=True)
class Issue:
    field: str
    code: str  # id_format, required, not_allowed, type, range, unknown_field, missing_ref, id_immutable, self_ref
    message: str


def split_multi(value: Any, separator: str | None) -> list[str]:
    """Codes held in one cell: ``"UV-001;UV-002"`` -> two codes. A single code stays one."""
    if value is None:
        return []
    text = str(value)
    parts = text.split(separator) if separator else [text]
    return [p.strip() for p in parts if p.strip()]


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_record(
    schema: schema_mod.Schema,
    table: str,
    fields: Mapping[str, Any],
    *,
    known_ids: KnownIds,
    op: str = "create",
    key: str | None = None,
) -> list[Issue]:
    """Check one record. ``known_ids`` maps table key -> IDs that exist in Teable or in own drafts.

    For an update, ``fields`` holds only the changed fields: required is checked only for fields
    that are present, and the ID field may not change (``key`` is the record's ID)."""
    specs = schema_mod.fields_of(schema, table)
    id_name = schema_mod.id_field(schema, table)
    issues: list[Issue] = []

    for name in fields:
        if name not in specs:
            issues.append(Issue(name, "unknown_field", f"{table} has no field {name}"))

    if op == "create":
        issues += _check_id(schema, table, id_name, fields.get(id_name))
    elif id_name in fields and key is not None and fields[id_name] != key:
        issues.append(Issue(id_name, "id_immutable", f"{id_name} cannot be changed after commit"))

    own_id = fields.get(id_name) if op == "create" else key
    for name, spec in specs.items():
        if name == id_name and op == "create":
            continue  # handled by _check_id
        if name not in fields and op == "update":
            continue
        value = fields.get(name)
        if is_empty(value):
            if spec.get("required"):
                issues.append(Issue(name, "required", f"{name} is required"))
            continue
        issues += _check_value(name, spec, value)
        issues += _check_refs(table, name, spec, value, known_ids, own_id)
    return issues


def _check_id(schema: schema_mod.Schema, table: str, id_name: str, value: Any) -> list[Issue]:
    if is_empty(value):
        return [Issue(id_name, "required", f"{id_name} is required")]
    pattern = schema["tables"][table]["id"].get("pattern")
    example = schema["tables"][table]["id"].get("example", "")
    if pattern and not (isinstance(value, str) and re.fullmatch(pattern, value)):
        return [Issue(id_name, "id_format", f"{id_name} {value!r} does not match the format, for example {example}")]
    return []


def _check_value(name: str, spec: Mapping[str, Any], value: Any) -> list[Issue]:
    kind = spec["type"]
    if kind == "choice":
        if value not in spec["choices"]:
            return [Issue(name, "not_allowed", f"{name} {value!r} is not one of {', '.join(map(str, spec['choices']))}")]
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [Issue(name, "type", f"{name} must be a number")]
        if spec.get("integer") and float(value) != int(value):
            return [Issue(name, "type", f"{name} must be a whole number")]
        if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
            low, high = spec.get("min", "-inf"), spec.get("max", "inf")
            return [Issue(name, "range", f"{name} must be between {low} and {high}")]
    elif kind == "date":
        if not (isinstance(value, str) and DATE_RE.match(value)):
            return [Issue(name, "type", f"{name} must be a date like 2026-10-20")]
    elif not isinstance(value, str):
        return [Issue(name, "type", f"{name} must be text")]
    return []


def _check_refs(
    table: str, name: str, spec: Mapping[str, Any], value: Any, known_ids: KnownIds, own_id: Any
) -> list[Issue]:
    ref = spec.get("ref")
    if not ref:
        return []
    extra = set(spec.get("ref_extra") or [])
    issues: list[Issue] = []
    for code in split_multi(value, spec.get("multi")):
        if code in extra:
            continue
        if ref == table and code == own_id:
            issues.append(Issue(name, "self_ref", f"{name} cannot point at the record itself ({code})"))
        elif code not in known_ids.get(ref, ()):
            issues.append(Issue(name, "missing_ref", f"{name}: {code} does not exist in {ref} (Teable or your drafts)"))
    return issues


# ---- helpers that read the store -------------------------------------------


def known_ids_from(schema: schema_mod.Schema, store: Store) -> dict[str, set[str]]:
    """IDs of every table that exist in the cache, plus IDs of the user's own create drafts."""
    known: dict[str, set[str]] = {}
    for table, id_name in schema_mod.id_fields(schema).items():
        known[table] = store.cache_ids(table, id_name)
    for draft in store.list_drafts():
        if draft.is_new:
            known.setdefault(draft.table, set()).add(draft.key)
    return known


def validate_draft(schema: schema_mod.Schema, draft: Draft, known_ids: KnownIds) -> list[Issue]:
    return validate_record(
        schema, draft.table, draft.fields, known_ids=known_ids, op=draft.op, key=draft.key
    )


def validate_store_draft(schema: schema_mod.Schema, store: Store, draft_id: int) -> list[Issue]:
    """Validation state of one saved draft, as the draft list shows it."""
    return validate_draft(schema, store.get_draft(draft_id), known_ids_from(schema, store))
