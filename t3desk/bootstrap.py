"""Create the project's tables and fields in a Teable base from schema.yaml.

Safe to run again: it adds what is missing, changes nothing that exists and reports
every field whose type, unique flag or notNull flag differs from the schema.
It finishes by proving that Teable refuses a duplicate ID (the first-come rule).
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from t3desk import schema as schema_mod
from t3desk.teable_client import TeableClient, TeableError

log = logging.getLogger("t3desk.bootstrap")

TOKEN_ENV = "T3DESK_TEABLE_TOKEN"


class BootstrapError(Exception):
    """Bootstrap cannot continue or cannot guarantee the first-come ID rule."""


@dataclass
class Mismatch:
    table: str
    field: str
    what: str  # "type" | "unique" | "notNull"
    expected: Any
    actual: Any

    def __str__(self) -> str:
        return f"{self.table}.{self.field}: {self.what} is {self.actual!r}, schema says {self.expected!r}"


@dataclass
class BootstrapReport:
    base_id: str = ""
    table_ids: dict[str, str] = field(default_factory=dict)
    created_tables: list[str] = field(default_factory=list)
    created_fields: list[str] = field(default_factory=list)  # "table.field"
    created_settings: list[str] = field(default_factory=list)  # cai_dat keys
    obsolete_settings: list[str] = field(default_factory=list)  # old rows found, kept, never read
    mismatches: list[Mismatch] = field(default_factory=list)
    scratch_table_id: str = ""
    scratch_ok: bool = False

    @property
    def changed(self) -> bool:
        """True when this run created anything in Teable (scratch test record excluded)."""
        return bool(self.created_tables or self.created_fields or self.created_settings)

    @property
    def has_differences(self) -> bool:
        """True when existing fields do not match the schema (they are reported, never changed)."""
        return bool(self.mismatches)

    def lines(self) -> list[str]:
        out = [f"base: {self.base_id}"]
        out += [f"created table: {t}" for t in self.created_tables]
        out += [f"created field: {f}" for f in self.created_fields]
        out += [f"created setting: {k}" for k in self.created_settings]
        if self.obsolete_settings:
            out.append("OBSOLETE settings kept and no longer used (old unit, million VND per unit; "
                       "the new rates are the vnd_per_* rows, VND per 1 unit): "
                       + ", ".join(self.obsolete_settings))
        out += [f"DIFFERENCE {m}" for m in self.mismatches]
        if not (self.changed or self.mismatches):
            out.append("nothing to change, no differences")
        out.append("duplicate-ID check: " + ("refused as required" if self.scratch_ok else "NOT RUN"))
        return out


def run_bootstrap(
    client: TeableClient,
    *,
    base_id: str | None = None,
    project_name: str | None = None,
    space_id: str | None = None,
    schema: schema_mod.Schema | None = None,
    settings: dict[str, Any] | None = None,
    settings_path: Path | None = None,
    scratch_check: bool = True,
    progress: Callable[[str], None] | None = None,
) -> BootstrapReport:
    """Create or verify every table and field. Fills ``settings`` with base_id and table_ids.

    Raises BootstrapError if the duplicate-ID check shows Teable does not enforce the unique flag.
    """
    sch = schema or schema_mod.load_schema()
    settings = settings if settings is not None else {}
    say = progress or (lambda text: None)
    report = BootstrapReport()

    report.base_id = _resolve_base(client, base_id, project_name, space_id)
    say(f"base {report.base_id}")
    existing = {t["name"]: t["id"] for t in client.list_tables(report.base_id)}

    for table in schema_mod.table_keys(sch):
        payloads = schema_mod.table_field_payloads(sch, table)
        report.table_ids[table] = _ensure_table(client, report, existing, table, payloads, sch)
        say(f"table {table}")

    _write_default_settings(client, report, sch, project_name)

    settings["base_id"] = report.base_id
    settings["table_ids"] = dict(report.table_ids)
    if scratch_check:
        _scratch_duplicate_check(client, report, existing, sch)
        settings["scratch_table_id"] = report.scratch_table_id
    if settings_path is not None:
        save_settings(settings, settings_path)
    return report


def _resolve_base(client: TeableClient, base_id: str | None, project_name: str | None,
                  space_id: str | None) -> str:
    if base_id:
        return base_id
    if not (project_name and space_id):
        raise BootstrapError("give either a base id, or a project name together with a space id")
    return client.create_base(space_id, project_name)["id"]


def _ensure_table(
    client: TeableClient, report: BootstrapReport, existing: dict[str, str],
    table: str, payloads: list[dict[str, Any]], sch: schema_mod.Schema,
) -> str:
    """Create the table, or add missing fields and report differences on an existing one."""
    if table not in existing:
        created = client.create_table(report.base_id, table, payloads)
        existing[table] = created["id"]
        report.created_tables.append(table)
        return created["id"]
    table_id = existing[table]
    _sync_fields(client, report, table, table_id, payloads)
    return table_id


def _sync_fields(client: TeableClient, report: BootstrapReport, table: str, table_id: str,
                 payloads: list[dict[str, Any]]) -> None:
    actual = {f["name"]: f for f in client.list_fields(table_id)}
    for wanted in payloads:
        name = wanted["name"]
        if name not in actual:
            client.create_field(table_id, wanted)
            report.created_fields.append(f"{table}.{name}")
            continue
        report.mismatches.extend(_compare(table, wanted, actual[name]))


def _compare(table: str, wanted: dict[str, Any], actual: dict[str, Any]) -> list[Mismatch]:
    name = wanted["name"]
    found: list[Mismatch] = []
    if actual.get("type") != wanted["type"]:
        found.append(Mismatch(table, name, "type", wanted["type"], actual.get("type")))
    for flag in ("unique", "notNull"):
        expected, got = bool(wanted.get(flag)), bool(actual.get(flag))
        if expected != got:
            found.append(Mismatch(table, name, flag, expected, got))
    return found


def _write_default_settings(client: TeableClient, report: BootstrapReport, sch: schema_mod.Schema,
                            project_name: str | None) -> None:
    """Insert default cai_dat rows whose key is missing. Existing rows are never touched."""
    table_id = report.table_ids["cai_dat"]
    key_field = schema_mod.id_field(sch, "cai_dat")
    present = {r["fields"].get(key_field) for r in client.list_all_records(table_id)}
    obsolete = sch.get("exchange_rates", {}).get("obsolete_keys", [])
    report.obsolete_settings = [k for k in obsolete if k in present]
    for row in sch["defaults"]["cai_dat"]:
        key = row[key_field]
        if key in present:
            continue
        fields = {key_field: key}
        value = str(row.get("gia_tri", "")).replace("$project_name", project_name or "")
        if value:
            fields["gia_tri"] = value
        try:
            client.create_record(table_id, fields)
        except TeableError as exc:
            if not exc.is_unique_violation:  # a parallel bootstrap won the race: fine
                raise
            continue
        report.created_settings.append(key)


def _scratch_duplicate_check(client: TeableClient, report: BootstrapReport,
                             existing: dict[str, str], sch: schema_mod.Schema) -> None:
    """Create two records with the same ID in a scratch table; the second must be refused."""
    spec = sch["scratch_table"]
    name, id_name = spec["name"], spec["id_field"]
    payloads = schema_mod.scratch_field_payloads(sch)
    table_id = _ensure_table(client, report, existing, name, payloads, sch)
    report.scratch_table_id = table_id
    # Not counted as a schema table or a change: it only exists for this test.
    if name in report.created_tables:
        report.created_tables.remove(name)
    scratch_id = "SCRATCH-" + uuid.uuid4().hex[:10]
    client.create_record(table_id, {id_name: scratch_id})
    try:
        client.create_record(table_id, {id_name: scratch_id})
    except TeableError as exc:
        if exc.is_unique_violation:
            report.scratch_ok = True
            return
        raise BootstrapError(
            f"Could not finish the duplicate-ID check: {exc}. Run bootstrap again when Teable is healthy."
        ) from exc
    raise BootstrapError(
        "Teable accepted two records with the same ID in the scratch table "
        f"'{name}'. The unique flag is not enforced, so the first-come ID rule would not hold. "
        "Do not use this base until unique fields work (check the Teable version and its database)."
    )


def save_settings(settings: dict[str, Any], path: Path) -> None:
    """Write settings as JSON. Tokens are never part of this dict; refuse if one sneaks in."""
    if any("token" in key.lower() for key in settings):
        raise BootstrapError("settings must not contain a token")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


# ---- command line -----------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="Teable address, e.g. http://nas:3000")
    parser.add_argument("--token", help=f"Teable token (or set {TOKEN_ENV}, or you will be asked)")
    parser.add_argument("--base-id", help="existing base to fill")
    parser.add_argument("--project-name", help="project name (also names a new base)")
    parser.add_argument("--space-id", help="space for a new base (needed with --project-name only)")
    parser.add_argument("--settings-file", type=Path, help="write base id and table ids here (JSON)")


def run_cli(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get(TOKEN_ENV) or getpass.getpass("Teable token: ")
    settings: dict[str, Any] = {"teable_url": args.url.rstrip("/")}
    try:
        with TeableClient(args.url, token) as client:
            client.ping()
            report = run_bootstrap(
                client, base_id=args.base_id, project_name=args.project_name, space_id=args.space_id,
                settings=settings, settings_path=args.settings_file, progress=print,
            )
    except (TeableError, BootstrapError) as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 2
    print("\n".join(report.lines()))
    if not args.settings_file:
        print(json.dumps(settings, indent=2, ensure_ascii=False))
    return 1 if report.has_differences else 0
