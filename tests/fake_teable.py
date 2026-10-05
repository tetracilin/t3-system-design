"""In-process fake Teable server for tests (no network beyond 127.0.0.1).

Implements the calls t3desk/teable_client.py uses:

    GET   /api/space                             list spaces (the connection test)
    GET   /api/auth/user
    POST  /api/base                              create base
    GET   /api/base/{base}/table                 list tables
    POST  /api/base/{base}/table                 create table with fields
    GET   /api/table/{t}/field                   list fields
    POST  /api/table/{t}/field                   create field (unique / notNull)
    GET   /api/table/{t}/record                  take (max 1000), skip, filter, projection, fieldKeyType
    GET   /api/table/{t}/record/{r}
    POST  /api/table/{t}/record                  create (unique, notNull, choices enforced)
    PATCH /api/table/{t}/record/{r}              update

Shapes and messages mirror a real server (release.2026-08-19T02-25-59Z.2698), see
docs/notes/teable-live.md: errors are {"message", "status", "code", "data": {"domainCode"}};
a unique clash is HTTP 400 "... must have a unique value"; the create-record answer holds only
``id`` and the sent fields; GET/list add autoNumber, createdTime, lastModifiedTime at the top
level and the system fields in ``fields``; dates are returned as UTC timestamps; a duplicate
field or table name is accepted (a field gets " 2").

There is no DELETE route: any DELETE answers 405 and is logged, so tests can prove none was sent.

Test helpers: ``drop_unique``, ``drop_field``, ``set_delay``, ``fail_next``, ``seed``, ``stop`` /
``start`` (same port, state kept), ``request_log``, ``enforce_unique``.
Everything is guarded by one lock, so threads see the same atomic checks a database gives.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

# hours east of UTC for the date-field time zones the fake understands
TZ_OFFSET_HOURS = {"utc": 0, "UTC": 0, "Asia/Ho_Chi_Minh": 7}

SYSTEM_TYPES = {"autoNumber", "createdTime", "lastModifiedTime", "createdBy", "lastModifiedBy"}


class _HttpError(Exception):
    def __init__(self, status: int, message: str, domain_code: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.domain_code = domain_code


class FakeTeable:
    def __init__(self, *, enforce_unique: bool = True, strict_auth: bool = False,
                 users: dict[str, str] | None = None):
        self.enforce_unique = enforce_unique
        self.strict_auth = strict_auth
        self.users = dict(users or {})  # token -> user name
        self.request_log: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._tables: dict[str, dict[str, Any]] = {}
        self._bases: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._last_time = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self._delays: list[dict[str, Any]] = []
        self._failures: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0

    # ---- lifecycle ----------------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> FakeTeable:
        owner = self

        class Handler(_Handler):
            fake = owner

        class Server(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", self._port), Handler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> FakeTeable:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ---- test helpers -------------------------------------------------------

    def set_delay(self, seconds: float, *, method: str | None = None,
                  path_contains: str | None = None, count: int | None = None) -> None:
        """Sleep before handling matching requests (outside the data lock)."""
        self._delays.append({"seconds": seconds, "method": method, "path": path_contains, "count": count})

    def clear_delays(self) -> None:
        self._delays.clear()

    def fail_next(self, status: int = 503, message: str = "injected failure", *,
                  method: str | None = None, path_contains: str | None = None, count: int = 1) -> None:
        self._failures.append(
            {"status": status, "message": message, "method": method, "path": path_contains, "count": count}
        )

    def table_id(self, name: str) -> str:
        with self._lock:
            for table in self._tables.values():
                if table["name"] == name:
                    return table["id"]
        raise KeyError(name)

    def table_names(self) -> list[str]:
        with self._lock:
            return [t["name"] for t in self._tables.values()]

    def fields(self, table_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(self._table_by_name(table_name)["fields"]))

    def records(self, table_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(self._table_by_name(table_name)["records"]))

    def snapshot(self, *, skip_tables: tuple[str, ...] = ()) -> str:
        """Stable JSON of tables, fields and records, for "nothing changed" comparisons."""
        with self._lock:
            tables = {t["name"]: t for t in self._tables.values() if t["name"] not in skip_tables}
            return json.dumps(tables, sort_keys=True, ensure_ascii=False)

    def drop_unique(self, table_name: str, field_name: str) -> None:
        with self._lock:
            self._field(self._table_by_name(table_name), field_name)["unique"] = False

    def drop_field(self, table_name: str, field_name: str) -> None:
        with self._lock:
            table = self._table_by_name(table_name)
            table["fields"] = [f for f in table["fields"] if f["name"] != field_name]

    def seed(self, table_name: str, fields: dict[str, Any], *, user: str = "seed") -> dict[str, Any]:
        """Insert a record directly (as ``user``), enforcing the same rules as the API."""
        with self._lock:
            return self._create_record(self._table_by_name(table_name), fields, user, typecast=True)

    # ---- internals (called with the lock held unless noted) -------------------

    def _table_by_name(self, name: str) -> dict[str, Any]:
        for table in self._tables.values():
            if table["name"] == name:
                return table
        raise KeyError(name)

    @staticmethod
    def _field(table: dict[str, Any], name: str) -> dict[str, Any]:
        for field in table["fields"]:
            if field["name"] == name:
                return field
        raise KeyError(name)

    def _next(self, kind: str) -> int:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return self._counters[kind]

    def _now(self) -> str:
        """Strictly increasing UTC timestamps, so created/modified order is always decidable."""
        self._last_time = max(datetime.now(timezone.utc), self._last_time + timedelta(milliseconds=1))
        return self._last_time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self._last_time.microsecond // 1000:03d}Z"

    def _user_for(self, token: str) -> dict[str, str]:
        if token in self.users:
            return {"id": "usr_" + token, "name": self.users[token]}
        if self.strict_auth:
            raise _HttpError(401, "Unauthorized")
        return {"id": "usr_" + token, "name": token}

    def _add_field(self, table: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
        name = spec.get("name")
        if not name or "type" not in spec:
            raise _HttpError(400, "field needs name and type")
        if spec.get("notNull") and table["records"]:
            raise _HttpError(
                400, f'Cannot mark field "{name}" as required because existing records contain empty values.',
                "validation.field.required_existing_values",
            )
        while any(f["name"] == name for f in table["fields"]):  # real Teable renames, it does not refuse
            name = f"{name} 2"
        field = {
            "id": f"fld{self._next('field'):06d}",
            "name": name,
            "type": spec["type"],
            "options": spec.get("options") or {},
            "unique": bool(spec.get("unique")),
            "notNull": bool(spec.get("notNull")),
            "isPrimary": not table["fields"],
        }
        table["fields"].append(field)
        return field

    def _create_table(self, base_id: str, body: dict[str, Any]) -> dict[str, Any]:
        name = body.get("name")
        if not name:
            raise _HttpError(400, "table name required")
        table = {"id": f"tbl{self._next('table'):06d}", "baseId": base_id, "name": name,
                 "fields": [], "records": []}
        self._tables[table["id"]] = table
        for spec in body.get("fields") or []:
            self._add_field(table, spec)
        if "records" not in body:  # real Teable adds blank starter rows when `records` is left out
            for _ in range(3):
                table["records"].append(self._blank_record(table))
        for rec in body.get("records") or []:
            self._create_record(table, rec.get("fields", {}), "table-create", typecast=True)
        return table

    def _blank_record(self, table: dict[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {"id": f"rec{self._next('record'):08d}", "fields": {}}
        now = self._now()
        record.update(autoNumber=len(table["records"]) + 1, createdTime=now, lastModifiedTime=now,
                      createdBy="usr_table-create", lastModifiedBy="usr_table-create")
        self._fill_system(table, record, "table-create", created=True)
        return record

    def _check_value(self, field: dict[str, Any], value: Any, typecast: bool) -> None:
        ftype = field["type"]
        if value is None:
            return
        if ftype == "singleSelect":
            names = [c["name"] for c in field["options"].get("choices", [])]
            if value not in names and not typecast:
                raise _HttpError(
                    400, f'Invalid value for field "{field["name"]}": Invalid option: expected one of '
                    + "|".join(f'"{n}"' for n in names), "validation.field.invalid_value")
        elif ftype == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise _HttpError(
                400, f'Invalid value for field "{field["name"]}": Invalid input: expected number, '
                f"received {type(value).__name__}", "validation.field.invalid_value")
        elif ftype in {"singleLineText", "longText", "date"} and not isinstance(value, str):
            raise _HttpError(
                400, f'Invalid value for field "{field["name"]}": Invalid input: expected string',
                "validation.field.invalid_value")

    def _unique_clash(self, table: dict[str, Any], field: dict[str, Any], value: Any,
                      ignore: str | None = None) -> bool:
        return any(
            r["id"] != ignore and r["fields"].get(field["name"]) == value for r in table["records"]
        )

    def _validate_and_apply(self, table: dict[str, Any], record: dict[str, Any],
                            values: dict[str, Any], typecast: bool, creating: bool) -> dict[str, Any]:
        by_name = {f["name"]: f for f in table["fields"]}
        merged = dict(record["fields"])
        for name, value in values.items():
            if name not in by_name:
                raise _HttpError(404, f'Field "{name}" does not exist in this table', "field.key_not_found")
            if by_name[name]["type"] in SYSTEM_TYPES:
                continue  # real Teable silently ignores a value sent for a computed field
            self._check_value(by_name[name], value, typecast)
            if value is None or value == "":
                merged.pop(name, None)
            elif by_name[name]["type"] == "date":
                merged[name] = self._date_to_utc(by_name[name], value)
            else:
                merged[name] = value
        for field in table["fields"]:
            if field["type"] in SYSTEM_TYPES:
                continue
            value = merged.get(field["name"])
            verb = "insert" if creating else "update"
            if field["notNull"] and creating and field["name"] not in values:
                raise _HttpError(
                    400, f'Cannot create record: field "{field["name"]}" violates not-null constraint',
                    "validation.field.not_null")
            if field["notNull"] and (creating or field["name"] in values) and value in (None, ""):
                raise _HttpError(
                    400, f"Cannot complete {verb}: field {field['id']} cannot be empty",
                    "validation.field.not_null")
            if field["unique"] and self.enforce_unique and value not in (None, "") \
                    and self._unique_clash(table, field, value, ignore=None if creating else record["id"]):
                raise _HttpError(
                    400, f"Cannot complete {verb}: field {field['id']} must have a unique value",
                    "validation.field.unique")
        return merged

    @staticmethod
    def _date_to_utc(field: dict[str, Any], value: str) -> str:
        """"2026-10-05" is local midnight in the field's time zone; Teable returns it as UTC."""
        try:
            day = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return value
        zone = field["options"].get("formatting", {}).get("timeZone", "utc")
        moment = day - timedelta(hours=TZ_OFFSET_HOURS.get(zone, 0))
        return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _create_record(self, table: dict[str, Any], values: dict[str, Any], user: str,
                       typecast: bool = False) -> dict[str, Any]:
        record = {"id": f"rec{self._next('record'):08d}", "fields": {}}
        record["fields"] = self._validate_and_apply(table, record, values, typecast, creating=True)
        now = self._now()
        record["autoNumber"] = len([1 for _ in table["records"]]) + 1 + table.get("auto_offset", 0)
        record["createdTime"] = now
        record["lastModifiedTime"] = now
        record["createdBy"] = "usr_" + user
        record["lastModifiedBy"] = "usr_" + user
        self._fill_system(table, record, user, created=True)
        table["records"].append(record)
        return record

    def _fill_system(self, table: dict[str, Any], record: dict[str, Any], user: str, created: bool) -> None:
        who = {"id": "usr_" + user, "title": user, "email": f"{user}@fake.local"}
        for field in table["fields"]:
            kind, name = field["type"], field["name"]
            if kind == "autoNumber":
                record["fields"][name] = record["autoNumber"]
            elif kind == "createdTime":
                record["fields"][name] = record["createdTime"]
            elif kind == "lastModifiedTime":
                record["fields"][name] = record["lastModifiedTime"]
            elif kind == "createdBy" and created:
                record["fields"][name] = who
            elif kind == "lastModifiedBy":
                record["fields"][name] = who

    def _render(self, table: dict[str, Any], record: dict[str, Any], key_type: str,
                projection: list[str] | None) -> dict[str, Any]:
        by_name = {f["name"]: f for f in table["fields"]}
        fields = {}
        for name, value in record["fields"].items():
            if name not in by_name or (projection and name not in projection):
                continue
            fields[by_name[name]["id"] if key_type == "id" else name] = value
        out = {k: v for k, v in record.items() if k != "fields"}
        out["fields"] = fields
        return json.loads(json.dumps(out))

    def _render_created(self, table: dict[str, Any], record: dict[str, Any], key_type: str) -> dict[str, Any]:
        """The create answer: id and the stored non-system fields, nothing else."""
        full = self._render(table, record, key_type, None)
        system_keys = {f["id"] if key_type == "id" else f["name"]
                       for f in table["fields"] if f["type"] in SYSTEM_TYPES}
        return {"id": full["id"], "fields": {k: v for k, v in full["fields"].items() if k not in system_keys}}

    def _matches(self, table: dict[str, Any], record: dict[str, Any], flt: dict[str, Any] | None) -> bool:
        if not flt:
            return True
        by_id = {f["id"]: f["name"] for f in table["fields"]}
        results = []
        for cond in flt.get("filterSet", []):
            name = by_id.get(cond.get("fieldId"), cond.get("fieldId"))
            actual = record["fields"].get(name)
            op = cond.get("operator")
            if op == "is":
                results.append(actual == cond.get("value"))
            elif op == "isNot":
                results.append(actual != cond.get("value"))
            elif op == "contains":
                results.append(str(cond.get("value")) in str(actual or ""))
            else:
                raise _HttpError(400, f"unsupported filter operator {op}")
        return all(results) if flt.get("conjunction", "and") == "and" else any(results)

    # ---- request dispatch ---------------------------------------------------

    def handle(self, method: str, raw_path: str, headers: Any, body: bytes) -> tuple[int, Any]:
        parsed = urlparse(raw_path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        with self._lock:
            self.request_log.append({"method": method, "path": path, "query": query})
        self._apply_delay(method, path)
        try:
            self._maybe_fail(method, path)
            token = self._token(headers)
            data = json.loads(body) if body else {}
            with self._lock:
                return self._route(method, path, query, data, token)
        except _HttpError as exc:
            body: dict[str, Any] = {
                "message": exc.message, "status": exc.status,
                "code": {401: "unauthorized", 404: "not_found"}.get(exc.status, "validation_error"),
            }
            if exc.domain_code:
                body["data"] = {"domainCode": exc.domain_code}
            return exc.status, body

    def _apply_delay(self, method: str, path: str) -> None:
        total = 0.0
        with self._lock:
            for rule in list(self._delays):
                if rule["method"] in (None, method) and (rule["path"] is None or rule["path"] in path):
                    total += rule["seconds"]
                    if rule["count"] is not None:
                        rule["count"] -= 1
                        if rule["count"] <= 0:
                            self._delays.remove(rule)
        if total:
            time.sleep(total)

    def _maybe_fail(self, method: str, path: str) -> None:
        with self._lock:
            for rule in list(self._failures):
                if rule["method"] in (None, method) and (rule["path"] is None or rule["path"] in path):
                    rule["count"] -= 1
                    if rule["count"] <= 0:
                        self._failures.remove(rule)
                    raise _HttpError(rule["status"], rule["message"])

    @staticmethod
    def _token(headers: Any) -> str:
        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            raise _HttpError(401, "Unauthorized")
        return auth[7:].strip()

    def _route(self, method: str, path: str, query: dict[str, list[str]], data: dict[str, Any],
               token: str) -> tuple[int, Any]:
        user = self._user_for(token)
        parts = [p for p in path.split("/") if p]  # api, ...
        if parts == ["api", "space"] and method == "GET":
            return 200, [{"id": "spcfake000000000001", "name": "T3", "avatar": None, "role": "owner"}]
        if parts[:2] == ["api", "auth"] and parts[2:] == ["user"] and method == "GET":
            return 200, {"id": user["id"], "name": user["name"], "email": f"{user['name']}@fake.local"}
        if parts == ["api", "base"] and method == "POST":
            if not data.get("name"):
                raise _HttpError(400, "base name required")
            base_id = f"bse{self._next('base'):06d}"
            self._bases[base_id] = data["name"]
            return 201, {"id": base_id, "name": data["name"]}
        if len(parts) == 4 and parts[:2] == ["api", "base"] and parts[3] == "table":
            base_id = parts[2]
            if method == "GET":
                return 200, [{"id": t["id"], "name": t["name"]} for t in self._tables.values()
                             if t["baseId"] == base_id]
            if method == "POST":
                table = self._create_table(base_id, data)
                return 201, {"id": table["id"], "name": table["name"],
                             "fields": json.loads(json.dumps(table["fields"]))}
        if len(parts) >= 4 and parts[:2] == ["api", "table"]:
            table = self._tables.get(parts[2])
            if table is None:
                raise _HttpError(404, f"table {parts[2]} not found")
            return self._route_table(method, parts[3:], query, data, table, user)
        raise _HttpError(405 if method == "DELETE" else 404, f"no route for {method} {path}")

    def _route_table(self, method: str, rest: list[str], query: dict[str, list[str]],
                     data: dict[str, Any], table: dict[str, Any], user: dict[str, str]) -> tuple[int, Any]:
        if rest == ["field"]:
            if method == "GET":
                return 200, json.loads(json.dumps(table["fields"]))
            if method == "POST":
                return 201, json.loads(json.dumps(self._add_field(table, data)))
        if rest == ["record"]:
            if method == "GET":
                return 200, {"records": self._list(table, query)}
            if method == "POST":
                typecast = bool(data.get("typecast"))
                created = []
                snapshot = list(table["records"])
                try:
                    for item in data.get("records", []):
                        created.append(self._create_record(table, item.get("fields", {}), user["name"], typecast))
                except _HttpError:
                    table["records"] = snapshot  # all or nothing, like a transaction
                    raise
                key = data.get("fieldKeyType", "name")
                return 201, {"records": [self._render_created(table, r, key) for r in created]}
        if len(rest) == 2 and rest[0] == "record":
            record = next((r for r in table["records"] if r["id"] == rest[1]), None)
            if record is None:
                raise _HttpError(404, f"record {rest[1]} not found")
            key = (query.get("fieldKeyType") or [data.get("fieldKeyType", "name")])[0]
            if method == "GET":
                return 200, self._render(table, record, key, None)
            if method == "PATCH":
                values = data.get("record", {}).get("fields", {})
                record["fields"] = self._validate_and_apply(
                    table, record, values, bool(data.get("typecast")), creating=False)
                record["lastModifiedTime"] = self._now()
                record["lastModifiedBy"] = "usr_" + user["name"]
                self._fill_system(table, record, user["name"], created=False)
                answer = self._render(table, record, key, None)  # the PATCH answer: id and fields only
                return 200, {"id": answer["id"], "fields": answer["fields"]}
        raise _HttpError(405 if method == "DELETE" else 404, f"no route for {method} /{'/'.join(rest)}")

    def _list(self, table: dict[str, Any], query: dict[str, list[str]]) -> list[dict[str, Any]]:
        take = int((query.get("take") or ["100"])[0])
        skip = int((query.get("skip") or ["0"])[0])
        if not 1 <= take <= 1000:
            raise _HttpError(
                400, 'Validation error: Can\'t take more than 1000 records, please reduce take count at "take"'
                if take > 1000 else 'Validation error: You should at least take 1 record at "take"')
        key = (query.get("fieldKeyType") or ["name"])[0]
        try:
            flt = json.loads(query["filter"][0]) if query.get("filter") else None
        except ValueError:
            raise _HttpError(400, "filter is not valid JSON") from None
        projection = query.get("projection")
        rows = [r for r in table["records"] if self._matches(table, r, flt)]
        return [self._render(table, r, key, projection) for r in rows[skip:skip + take]]


class _Handler(BaseHTTPRequestHandler):
    fake: FakeTeable
    protocol_version = "HTTP/1.0"  # one request per connection: stop() really stops service

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        status, payload = self.fake.handle(self.command, self.path, self.headers, body)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - keep test output quiet
        pass
