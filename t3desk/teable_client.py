"""The only module that talks HTTP to Teable.

Paths and payloads were checked against a real Teable (release.2026-08-19T02-25-59Z.2698,
EE, PostgreSQL) on 5 Oct 2026; see docs/notes/teable-live.md for what was seen. Re-check
them whenever the server is upgraded.

There is deliberately no delete call: records are retired by status, never removed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import httpx

log = logging.getLogger("t3desk.teable")

MAX_TAKE = 1000  # Teable's maximum page size for list records
RETRY_STATUSES = frozenset({429, 502, 503, 504})

Record = dict[str, Any]

# Teable answers a date written as 2026-10-05 in a UTC date field as this timestamp.
_UTC_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.000)?Z$")


class TeableError(Exception):
    """A Teable call failed. ``status`` is None when no HTTP answer arrived."""

    def __init__(self, message: str, *, status: int | None = None, method: str = "", path: str = "",
                 code: str = "", domain_code: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.method = method
        self.path = path
        self.code = code  # e.g. "validation_error"
        self.domain_code = domain_code  # e.g. "validation.field.unique"

    @property
    def is_unique_violation(self) -> bool:
        """True when the server refused a write because a unique field already holds the value.

        Real Teable answers HTTP 400, code ``validation_error``, domainCode
        ``validation.field.unique`` and "... must have a unique value"."""
        if self.status is None or not 400 <= self.status < 500:
            return False
        if self.domain_code:
            return self.domain_code == "validation.field.unique"
        text = self.message.lower()
        return self.status == 409 or "unique" in text or "duplicate" in text

    def __str__(self) -> str:
        where = f"{self.method} {self.path}".strip()
        if not where and self.status is None:
            return self.message
        status = f"HTTP {self.status}" if self.status is not None else "no answer"
        return f"{where}: {status}: {self.message}"


class TeableConnectionError(TeableError):
    """The server could not be reached (refused, timed out, DNS)."""


class UniqueFlagError(TeableError):
    """One or more ID fields have lost their unique flag; committing is unsafe."""

    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__("unique flag missing on ID field(s): " + ", ".join(fields))


class TeableClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        backoff: float = 0.4,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._retries = max(0, retries)
        self._backoff = backoff
        self._date_fields: dict[str, list[str]] = {}
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def __repr__(self) -> str:  # never show the token
        return f"TeableClient({self._base_url!r})"

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TeableClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- low level ----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        """Send one request. Only reads are retried after a server error; writes are
        retried only when the connection was never made, so a create cannot run twice."""
        is_read = method == "GET"
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, params=params, json=json_body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt < self._retries:
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise self._connection_error(exc, method, path) from exc
            except httpx.TransportError as exc:
                if is_read and attempt < self._retries:
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise self._connection_error(exc, method, path) from exc
            if is_read and response.status_code in RETRY_STATUSES and attempt < self._retries:
                self._sleep(attempt)
                attempt += 1
                continue
            return self._parse(response, method, path)

    def _sleep(self, attempt: int) -> None:
        time.sleep(self._backoff * (2**attempt))

    @staticmethod
    def _connection_error(exc: Exception, method: str, path: str) -> TeableConnectionError:
        reason = type(exc).__name__ + (f": {exc}" if str(exc) else "")
        return TeableConnectionError(f"cannot reach Teable ({reason})", method=method, path=path)

    @staticmethod
    def _parse(response: httpx.Response, method: str, path: str) -> Any:
        if response.is_success:
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise TeableError(
                    "server answered with something that is not JSON",
                    status=response.status_code, method=method, path=path,
                ) from exc
        message = response.text[:500]
        code = domain_code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("message") or body.get("error") or message)
                code = str(body.get("code") or "")
                data = body.get("data")
                if isinstance(data, dict):
                    domain_code = str(data.get("domainCode") or "")
        except ValueError:
            pass
        raise TeableError(
            message, status=response.status_code, method=method, path=path,
            code=code, domain_code=domain_code,
        )

    # ---- connection and structure -------------------------------------------

    def ping(self) -> dict[str, Any]:
        """Test address and token. Returns ``{"user": {...} | None, "spaces": [...]}``.

        ``GET /api/space`` is the test because it works for scoped tokens, while
        ``/api/auth/user/me`` answers 403 for them. A bad token answers 401. The user is read
        from ``/api/auth/user`` when that is allowed; an anonymous identity is refused."""
        spaces = self._request("GET", "/api/space")
        user: dict[str, Any] | None = None
        try:
            user = self._request("GET", "/api/auth/user")
        except TeableConnectionError:
            raise
        except TeableError as exc:
            if exc.status not in (401, 403, 404):
                raise
        if isinstance(user, dict) and _is_anonymous(user):
            raise TeableError("the token was not accepted: Teable treats this client as anonymous",
                              status=401, method="GET", path="/api/auth/user")
        return {"user": user if isinstance(user, dict) else None,
                "spaces": spaces if isinstance(spaces, list) else []}

    def create_base(self, space_id: str, name: str) -> dict[str, Any]:
        return self._request("POST", "/api/base", json_body={"spaceId": space_id, "name": name})

    def list_tables(self, base_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/base/{base_id}/table")

    def create_table(self, base_id: str, name: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a table with its fields; the first field becomes the primary field.
        ``records`` is sent empty so Teable does not add blank starter rows."""
        body = {"name": name, "fields": fields, "records": []}
        return self._request("POST", f"/api/base/{base_id}/table", json_body=body)

    def list_fields(self, table_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/table/{table_id}/field")

    def create_field(self, table_id: str, field: dict[str, Any]) -> dict[str, Any]:
        """Create one field. Teable does NOT refuse a name that exists: it silently makes
        "name 2". Callers must check ``list_fields`` first (bootstrap does)."""
        self._date_fields.pop(table_id, None)
        return self._request("POST", f"/api/table/{table_id}/field", json_body=field)

    def _date_field_names(self, table_id: str) -> list[str]:
        if table_id not in self._date_fields:
            self._date_fields[table_id] = [
                f["name"] for f in self.list_fields(table_id) if f.get("type") == "date"
            ]
        return self._date_fields[table_id]

    def _plain_dates(self, table_id: str, record: Record) -> Record:
        """Turn "2026-10-05T00:00:00.000Z" in date fields back into "2026-10-05"."""
        fields = record.get("fields")
        if not isinstance(fields, dict):
            return record
        names = [n for n in self._date_field_names(table_id) if isinstance(fields.get(n), str)]
        for name in names:
            match = _UTC_MIDNIGHT.match(fields[name])
            if match:
                fields[name] = match.group(1)
        return record

    # ---- records ------------------------------------------------------------

    def list_records(
        self,
        table_id: str,
        *,
        take: int = MAX_TAKE,
        skip: int = 0,
        filter: dict[str, Any] | None = None,  # noqa: A002 - Teable's parameter name
        projection: list[str] | None = None,
        field_key_type: str = "name",
    ) -> list[Record]:
        """One page of records. ``take`` may not exceed 1000."""
        if not 1 <= take <= MAX_TAKE:
            raise ValueError(f"take must be between 1 and {MAX_TAKE}, got {take}")
        params: dict[str, Any] = {"take": take, "skip": skip, "fieldKeyType": field_key_type}
        if filter is not None:
            params["filter"] = json.dumps(filter, separators=(",", ":"), ensure_ascii=False)
        if projection:
            params["projection"] = list(projection)
        data = self._request("GET", f"/api/table/{table_id}/record", params=params)
        if field_key_type != "name":
            return data["records"]
        return [self._plain_dates(table_id, r) for r in data["records"]]

    def iter_records(
        self,
        table_id: str,
        *,
        page_size: int = MAX_TAKE,
        filter: dict[str, Any] | None = None,  # noqa: A002
        projection: list[str] | None = None,
        field_key_type: str = "name",
        progress: Callable[[int], None] | None = None,
    ) -> Iterator[Record]:
        """Walk a whole table page by page; ``progress`` receives the count so far."""
        skip = 0
        while True:
            page = self.list_records(
                table_id, take=page_size, skip=skip, filter=filter,
                projection=projection, field_key_type=field_key_type,
            )
            yield from page
            skip += len(page)
            if progress is not None:
                progress(skip)
            if len(page) < page_size:
                return

    def list_all_records(self, table_id: str, **kwargs: Any) -> list[Record]:
        return list(self.iter_records(table_id, **kwargs))

    def find_by_field(self, table_id: str, field: str, value: str) -> list[Record]:
        """Records whose ``field`` equals ``value`` exactly."""
        by_name = {f["name"]: f["id"] for f in self.list_fields(table_id)}
        if field not in by_name:
            raise TeableError(f"field {field!r} not found", method="GET", path=f"/api/table/{table_id}/field")
        flt = {"conjunction": "and", "filterSet": [{"fieldId": by_name[field], "operator": "is", "value": value}]}
        return self.list_records(table_id, filter=flt, take=MAX_TAKE)

    def get_record(self, table_id: str, record_id: str, *, field_key_type: str = "name") -> Record:
        """One record with ``lastModifiedTime``, ``createdTime`` and ``autoNumber`` at the top level."""
        record = self._request(
            "GET", f"/api/table/{table_id}/record/{record_id}", params={"fieldKeyType": field_key_type}
        )
        return self._plain_dates(table_id, record) if field_key_type == "name" else record

    def create_record(self, table_id: str, fields: dict[str, Any], *, typecast: bool = False) -> Record:
        """Create exactly one record (no batch create, so one conflict cannot fail others).

        The answer holds only ``id`` and the fields that were sent: NO createdTime, autoNumber
        or system fields. Read the record back (``find_by_field`` / ``get_record``) for those."""
        body = {"fieldKeyType": "name", "typecast": typecast, "records": [{"fields": fields}]}
        data = self._request("POST", f"/api/table/{table_id}/record", json_body=body)
        return self._plain_dates(table_id, data["records"][0])

    def update_record(
        self, table_id: str, record_id: str, fields: dict[str, Any], *, typecast: bool = False
    ) -> Record:
        """Update one record; a value of None clears the field. The answer holds the whole record
        in ``fields`` (system fields included) but no top-level lastModifiedTime."""
        body = {"fieldKeyType": "name", "typecast": typecast, "record": {"fields": fields}}
        record = self._request("PATCH", f"/api/table/{table_id}/record/{record_id}", json_body=body)
        return self._plain_dates(table_id, record)

    # ---- safety net for the first-come ID rule ------------------------------

    def missing_unique_flags(
        self, table_ids: Mapping[str, str], id_field_names: Mapping[str, str]
    ) -> list[str]:
        """Return "table.field" for every ID field that is not flagged unique.

        ``table_ids`` maps table key -> Teable table id; ``id_field_names`` maps
        table key -> ID field name (see schema.id_fields)."""
        missing: list[str] = []
        for table, table_id in table_ids.items():
            wanted = id_field_names[table]
            fields = {f["name"]: f for f in self.list_fields(table_id)}
            if wanted not in fields:
                missing.append(f"{table}.{wanted} (field not found)")
            elif not fields[wanted].get("unique"):
                missing.append(f"{table}.{wanted}")
        return missing

    def ensure_unique_flags(
        self, table_ids: Mapping[str, str], id_field_names: Mapping[str, str]
    ) -> None:
        """Raise UniqueFlagError naming the fields if any ID field lost its unique flag."""
        missing = self.missing_unique_flags(table_ids, id_field_names)
        if missing:
            raise UniqueFlagError(missing)


def _is_anonymous(user: Mapping[str, Any]) -> bool:
    return any("anonymous" in str(user.get(k, "")).lower() for k in ("id", "name", "email"))


def record_author(record: Record) -> str:
    """Best available name of the record's creator, for "taken by ..." messages."""
    creator = record.get("fields", {}).get("created_by")
    if isinstance(creator, dict):
        return str(creator.get("title") or creator.get("id") or "")
    return str(creator or record.get("createdBy") or "")
