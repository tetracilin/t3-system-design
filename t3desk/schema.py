"""Loader and helpers for data/schema.yaml and data/labels_vi.yaml.

Nothing here knows a field name: everything is read from the YAML files.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"

Schema = dict[str, Any]

# schema type -> Teable field type
TEABLE_TYPES = {
    "text": "singleLineText",
    "longtext": "longText",
    "number": "number",
    "choice": "singleSelect",
    "date": "date",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a YAML mapping")
    return data


def load_schema(path: Path | None = None) -> Schema:
    return load_yaml(path or DATA_DIR / "schema.yaml")


def load_labels(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or DATA_DIR / "labels_vi.yaml")


def table_keys(schema: Schema) -> list[str]:
    return list(schema["tables"])


def id_field(schema: Schema, table: str) -> str:
    return schema["tables"][table]["id_field"]


def id_fields(schema: Schema) -> dict[str, str]:
    """Map table key -> name of its ID field."""
    return {name: spec["id_field"] for name, spec in schema["tables"].items()}


def fields_of(schema: Schema, table: str) -> dict[str, dict[str, Any]]:
    return schema["tables"][table]["fields"]


def teable_field_payload(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Build the body for Teable's create-field call from a schema field spec."""
    ftype = spec["type"]
    payload: dict[str, Any] = {"name": name, "type": TEABLE_TYPES[ftype]}
    if ftype == "choice":
        payload["options"] = {"choices": [{"name": c} for c in spec["choices"]]}
    elif ftype == "number":
        payload["options"] = {"formatting": {"type": "decimal", "precision": 4}}
    elif ftype == "date":
        payload["options"] = {
            "formatting": {"date": "YYYY-MM-DD", "time": "None", "timeZone": "Asia/Ho_Chi_Minh"}
        }
    if spec.get("unique"):
        payload["unique"] = True
    if spec.get("notNull"):
        payload["notNull"] = True
    return payload


def system_field_payloads(schema: Schema) -> list[dict[str, Any]]:
    return [{"name": f["name"], "type": f["type"]} for f in schema["system_fields"]]


def table_field_payloads(schema: Schema, table: str) -> list[dict[str, Any]]:
    """All fields for a table, ID field first (Teable uses the first as primary)."""
    payloads = [teable_field_payload(n, s) for n, s in fields_of(schema, table).items()]
    return payloads + system_field_payloads(schema)


def scratch_field_payloads(schema: Schema) -> list[dict[str, Any]]:
    spec = {"type": "text", "unique": True, "notNull": True}
    return [teable_field_payload(schema["scratch_table"]["id_field"], spec)]


def field_label(labels: dict[str, Any], table: str, field: str) -> str:
    override = labels.get("overrides", {}).get(table, {})
    if field in override:
        return override[field]
    if field in labels.get("fields", {}):
        return labels["fields"][field]
    return labels.get("system_fields", {}).get(field, field)


# ---- next free ID proposals -------------------------------------------------


def next_free_id(
    schema: Schema,
    table: str,
    existing: Iterable[str],
    *,
    prefix: str | None = None,
    parent: str | None = None,
) -> str | None:
    """Propose the next free ID of a table, or None when the kind cannot be proposed.

    ``existing`` holds IDs from Teable and from local drafts. ``prefix`` picks one of
    several prefixes (rfq: RFQ- or RFP-). ``parent`` is needed for tree IDs.
    """
    spec = schema["tables"][table]["id"]
    kind = spec["kind"]
    ids = [i for i in existing if i]
    if kind == "number":
        return _next_number(spec, ids, prefix)
    if kind == "letter":
        return _next_letter(spec, ids)
    if kind == "tree":
        return _next_tree(spec, ids, parent)
    return None


def _next_number(spec: dict[str, Any], ids: list[str], prefix: str | None) -> str:
    prefixes = spec.get("prefixes") or [spec["prefix"]]
    use = prefix or prefixes[0]
    if use not in prefixes:
        raise ValueError(f"unknown prefix {use!r}, expected one of {prefixes}")
    pattern = re.compile("^" + re.escape(use) + r"(\d+)$")
    numbers = [int(m.group(1)) for i in ids if (m := pattern.match(i))]
    number = max(numbers, default=0) + 1
    return f"{use}{number:0{spec.get('pad', 0)}d}"


def _next_letter(spec: dict[str, Any], ids: list[str]) -> str | None:
    pattern = re.compile("^" + re.escape(spec["prefix"]) + r"([A-Z])$")
    letters = [m.group(1) for i in ids if (m := pattern.match(i))]
    if not letters:
        return spec["prefix"] + "A"
    following = ord(max(letters)) + 1
    if following > ord("Z"):
        return None
    return spec["prefix"] + chr(following)


def _next_tree(spec: dict[str, Any], ids: list[str], parent: str | None) -> str:
    prefix = spec["prefix"]
    if parent is None:
        # Level 1 under the root: N1, N2, ...
        numbers = [int(i[len(prefix):]) for i in ids if re.fullmatch(re.escape(prefix) + r"[1-9]\d*", i)]
        return f"{prefix}{max(numbers, default=0) + 1}"
    pattern = re.compile("^" + re.escape(parent) + r"\.([1-9]\d*)$")
    numbers = [int(m.group(1)) for i in ids if (m := pattern.match(i))]
    return f"{parent}.{max(numbers, default=0) + 1}"
