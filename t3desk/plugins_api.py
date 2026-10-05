"""Plugin host: loads plugins, gives each one the ``api`` object, guards every send.

A plugin is a folder with ``plugin.yaml`` and ``plugin.py`` (section 9.1). The ``api`` object is
the only thing a plugin may use. Rules enforced here:

* a plugin writes only by creating or updating local drafts (never Teable, never commit);
* ``api.http`` refuses any host that is not in the manifest, and shows a preview first;
* every send is audited without secrets;
* a plugin that raises is disabled for the session and listed with its error. Nothing a plugin
  does can stop a commit, because the host catches everything at the call boundary.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from t3desk import rules
from t3desk import schema as schema_mod
from t3desk import store as store_mod
from t3desk import validation
from t3desk.store import Draft, Store

log = logging.getLogger("t3desk.plugins")

EVENTS = ("on_start", "after_commit", "on_job_poll")
ROLES = ("system_designer", "designer", "engineer", "sourcing", "pm")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
SCREEN_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")
CONFIG_HOST = re.compile(r"^\{config:([A-Za-z0-9_]+)\}$")
# Fields that belong to another system. T3 Desk never writes them (section 9.5).
PROTECTED_FIELDS: dict[str, frozenset[str]] = {"cong_viec": frozenset({"ma_ngoai", "dong_bo_luc"})}
DEFAULT_TIMEOUT = 15.0
SESSION = "session"  # a confirm hook returns this to skip the preview for the rest of the session


# ---------------------------------------------------------------- errors

class PluginError(Exception):
    """Base class for errors raised to a plugin by the api."""


class ManifestError(PluginError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


class HostNotAllowed(PluginError):
    """The URL's host is not in the plugin's manifest."""


class SendDeclined(PluginError):
    """The user did not confirm the preview. Not a plugin fault."""


class PluginHttpError(PluginError):
    """Network failure on a plugin call (message never holds a secret)."""


class DraftInvalid(PluginError):
    def __init__(self, table: str, issues: list[validation.Issue]):
        self.issues = issues
        super().__init__(f"draft for {table} is invalid: " + "; ".join(f"{i.field}: {i.message}" for i in issues))


class WriteNotAllowed(PluginError):
    """Table or field the plugin may not write."""


class RecordNotFound(PluginError):
    pass


class DraftExists(PluginError):
    pass


# ---------------------------------------------------------------- manifest

@dataclass(frozen=True)
class ConfigKey:
    key: str
    secret: bool = False
    label: str = ""
    default: str = ""


@dataclass(frozen=True)
class ActionSpec:
    id: str
    label: str
    screens: tuple[str, ...]
    roles: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    config: tuple[ConfigKey, ...] = ()
    hosts: tuple[str, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    events: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()  # tables the plugin may create drafts for (least privilege)

    def action(self, action_id: str) -> ActionSpec | None:
        return next((a for a in self.actions if a.id == action_id), None)

    def secret_keys(self) -> set[str]:
        return {c.key for c in self.config if c.secret}


def _as_list(value: Any, name: str, problems: list[str]) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{name} must be a list")
        return []
    return value


def parse_manifest(raw: Any, known_tables: Iterable[str] | None = None) -> Manifest:
    """Validate a parsed ``plugin.yaml``. Raises ManifestError listing every problem."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise ManifestError(["plugin.yaml must be a mapping"])
    for key in ("id", "name", "version"):
        if not isinstance(raw.get(key), (str, int, float)) or not str(raw.get(key)).strip():
            problems.append(f"{key} is required")
    pid = str(raw.get("id", ""))
    if pid and not ID_PATTERN.match(pid):
        problems.append(f"id {pid!r} must be lowercase letters, digits and underscore")

    config: list[ConfigKey] = []
    for item in _as_list(raw.get("config"), "config", problems):
        if not isinstance(item, dict) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", str(item.get("key", ""))):
            problems.append(f"bad config entry {item!r}")
            continue
        config.append(ConfigKey(str(item["key"]), bool(item.get("secret", False)),
                                str(item.get("label", "")), str(item.get("default", ""))))
    keys = [c.key for c in config]
    if len(keys) != len(set(keys)):
        problems.append("duplicate config keys")

    hosts: list[str] = []
    for host in _as_list(raw.get("hosts"), "hosts", problems):
        text = str(host).strip().lower() if host is not None else ""
        template = CONFIG_HOST.match(str(host)) if host is not None else None
        if template:
            if template.group(1) not in keys:
                problems.append(f"host template {host!r} names an unknown config key")
            hosts.append(str(host).strip())
        elif re.fullmatch(r"[a-z0-9.-]+(:\d+)?", text):
            hosts.append(text)
        else:
            problems.append(f"bad host {host!r}: use a bare host name, host:port or {{config:key}}")

    actions: list[ActionSpec] = []
    for item in _as_list(raw.get("actions"), "actions", problems):
        if not isinstance(item, dict) or not ID_PATTERN.match(str(item.get("id", ""))):
            problems.append(f"bad action entry {item!r}")
            continue
        screens = [str(s) for s in _as_list(item.get("screens"), "screens", problems)]
        roles = [str(r) for r in _as_list(item.get("roles"), "roles", problems)]
        for screen in screens:
            if not SCREEN_PATTERN.match(screen):
                problems.append(f"action {item['id']}: bad screen {screen!r} (expected screen.selection)")
        for role in roles:
            if role not in ROLES:
                problems.append(f"action {item['id']}: unknown role {role!r}")
        if not screens:
            problems.append(f"action {item['id']} names no screen")
        actions.append(ActionSpec(str(item["id"]), str(item.get("label", item["id"])), tuple(screens),
                                  tuple(roles) or ROLES))

    events = [str(e) for e in _as_list(raw.get("events"), "events", problems)]
    for event in events:
        if event not in EVENTS:
            problems.append(f"unknown event {event!r}; known: {', '.join(EVENTS)}")

    writes = [str(t) for t in _as_list(raw.get("writes"), "writes", problems)]
    if known_tables is not None:
        for table in writes:
            if table not in set(known_tables):
                problems.append(f"writes: unknown table {table!r}")

    if problems:
        raise ManifestError(problems)
    return Manifest(pid, str(raw["name"]), str(raw["version"]), tuple(config), tuple(hosts),
                    tuple(actions), tuple(events), tuple(writes))


# ---------------------------------------------------------------- host state

@dataclass
class PluginInfo:
    id: str
    path: Path
    manifest: Manifest | None = None
    state: str = "available"  # available | enabled | failed
    error: str = ""
    enabled: bool = False
    module: ModuleType | None = field(default=None, repr=False)
    actions: dict[str, Callable[..., Any]] = field(default_factory=dict, repr=False)
    handlers: dict[str, list[Callable[..., Any]]] = field(default_factory=dict, repr=False)

    @property
    def name(self) -> str:
        return self.manifest.name if self.manifest else self.id


@dataclass
class Job:
    id: int
    plugin: str
    label: str
    ref: str = ""
    state: str = "running"  # running | done | failed
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SendPreview:
    """What the user sees before anything leaves the machine."""

    plugin: str
    action: str
    method: str
    url: str
    host: str
    payload: Any
    record_ids: tuple[str, ...] = ()


@dataclass
class ActionResult:
    status: str  # ok | declined | error | unknown
    value: Any = None
    error: str = ""


@dataclass
class HttpReply:
    status: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


Confirm = Callable[[SendPreview], "bool | str"]


def flatten(record: Mapping[str, Any]) -> dict[str, Any]:
    """Teable record -> flat field dict (what rules.py reads), plus ``_record_id`` and ``_modified``."""
    out = dict(record.get("fields") or {})
    out["_record_id"] = record.get("id")
    out["_modified"] = record.get("lastModifiedTime")
    return out


def _norm(value: Any) -> Any:
    return "" if value is None else value


def changes_from_report(report: Any) -> list[dict[str, Any]]:
    """CommitReport -> the list of changes handed to ``after_commit`` handlers."""
    out: list[dict[str, Any]] = []
    for r in report.results:
        record = r.record or {}
        out.append({"table": r.table, "key": r.key, "status": r.status, "message": r.message,
                    "record_id": record.get("id"), "fields": dict(record.get("fields") or {})})
    return out


class PluginHost:
    """Finds, validates, enables, loads and runs plugins for one user on one machine."""

    def __init__(
        self,
        store: Store,
        schema: schema_mod.Schema,
        *,
        user: str,
        plugin_dirs: Iterable[str | Path],
        data_dir: str | Path,
        confirm: Confirm | None = None,
        today: Callable[[], date] = date.today,
        timeout: float = DEFAULT_TIMEOUT,
        keyring_module: ModuleType | None | bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        self.store = store
        self.schema = schema
        self.user = user
        self.plugin_dirs = [Path(p) for p in plugin_dirs]
        self.data_dir = Path(data_dir)
        self.confirm = confirm
        self.today = today
        self.timeout = timeout
        self._keyring = keyring_module
        self._transport = transport
        self.plugins: dict[str, PluginInfo] = {}
        self.notifications: list[tuple[str, str]] = []
        self.jobs: dict[int, Job] = {}
        self._job_seq = 0
        self._skip_preview: set[tuple[str, str]] = set()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._apis: dict[str, PluginApi] = {}
        self.audit_path = self.data_dir / "audit.jsonl"
        self.log_path = self.data_dir / "plugin.log"
        self.core = PluginApi(self, "core", None)

    # ---- discovery and enabling ---------------------------------------------

    def discover(self) -> list[PluginInfo]:
        """Scan the plugin folders. A bad manifest is listed as failed; it never raises."""
        found: dict[str, PluginInfo] = {}
        for base in self.plugin_dirs:
            if not base.is_dir():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir()):
                manifest_path = folder / "plugin.yaml"
                if not manifest_path.exists():
                    continue
                info = PluginInfo(id=folder.name, path=folder)
                try:
                    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                    info.manifest = parse_manifest(raw, schema_mod.table_keys(self.schema))
                    info.id = info.manifest.id
                    if not (folder / "plugin.py").exists():
                        raise ManifestError(["plugin.py is missing"])
                except (ManifestError, yaml.YAMLError, OSError) as exc:
                    info.state, info.error = "failed", f"manifest: {exc}"
                if info.id in found:
                    info.state, info.error = "failed", f"duplicate plugin id {info.id!r} in {folder}"
                    info.id = f"{info.id}@{folder}"
                info.enabled = info.id in self.enabled_ids()
                found[info.id] = info
        self.plugins = found
        return list(found.values())

    def enabled_ids(self) -> set[str]:
        return set(self.store.get_setting("plugins_enabled", []) or [])

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Per machine: stored in this user's SQLite settings, no token inside."""
        ids = self.enabled_ids()
        (ids.add if enabled else ids.discard)(plugin_id)
        self.store.set_setting("plugins_enabled", sorted(ids))
        if plugin_id in self.plugins:
            self.plugins[plugin_id].enabled = enabled

    # ---- config and secrets ---------------------------------------------------

    def set_config(self, plugin_id: str, key: str, value: str) -> None:
        self.store.set_setting(f"plugin.{plugin_id}.{key}", value)

    def get_config(self, plugin_id: str, key: str) -> str:
        info = self.plugins.get(plugin_id)
        spec = next((c for c in info.manifest.config if c.key == key), None) if info and info.manifest else None
        if spec is None:
            raise KeyError(f"plugin {plugin_id} declares no config key {key!r}")
        if spec.secret:
            raise WriteNotAllowed(f"{key} is a secret; use api.secret")
        return str(self.store.get_setting(f"plugin.{plugin_id}.{key}", spec.default) or "")

    def set_secret(self, plugin_id: str, key: str, value: str) -> str:
        return store_mod.save_secret(f"t3desk-plugin:{plugin_id}", key, value, fallback_dir=self.data_dir,
                                     keyring_module=self._keyring)

    def get_secret(self, plugin_id: str, key: str) -> str | None:
        info = self.plugins.get(plugin_id)
        if info is None or info.manifest is None or key not in info.manifest.secret_keys():
            raise KeyError(f"plugin {plugin_id} declares no secret {key!r}")
        return store_mod.load_secret(f"t3desk-plugin:{plugin_id}", key, fallback_dir=self.data_dir,
                                     keyring_module=self._keyring)

    def _secret_values(self, plugin_id: str | None = None) -> list[str]:
        values: list[str] = []
        for pid, info in self.plugins.items():
            if (plugin_id and pid != plugin_id) or info.manifest is None:
                continue
            for key in info.manifest.secret_keys():
                try:
                    found = store_mod.load_secret(f"t3desk-plugin:{pid}", key, fallback_dir=self.data_dir,
                                                  keyring_module=self._keyring)
                except OSError:
                    found = None
                if found and len(found) >= 4:
                    values.append(found)
        return values

    def scrub(self, text: str) -> str:
        """Replace every known secret value in ``text``. Used for logs, audit and error texts."""
        for secret in self._secret_values():
            text = text.replace(secret, "***")
        return text

    # ---- loading ---------------------------------------------------------------

    def load_all(self) -> None:
        """Import every enabled, valid plugin and call its ``register(api)``. Never raises."""
        for info in list(self.plugins.values()):
            info.enabled = info.id in self.enabled_ids()
            if info.enabled and info.state != "failed":
                self._load(info)

    def _load(self, info: PluginInfo) -> None:
        assert info.manifest is not None
        name = f"t3desk_plugin_{info.id}"
        try:
            spec = importlib.util.spec_from_file_location(name, info.path / "plugin.py")
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {info.path / 'plugin.py'}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError("plugin.py does not define register(api)")
            api = PluginApi(self, info.id, info)
            self._apis[info.id] = api
            register(api)
            info.module, info.state, info.error = module, "enabled", ""
        except Exception as exc:  # a plugin may raise anything; it must never stop the app
            sys.modules.pop(name, None)
            self.fail(info, exc, "load")

    def fail(self, info: PluginInfo, exc: BaseException, where: str) -> None:
        info.state = "failed"
        info.error = self.scrub(f"{where}: {type(exc).__name__}: {exc}")
        info.actions.clear()
        info.handlers.clear()
        log.error("plugin %s disabled for this session (%s)", info.id, info.error)
        self.plugin_log(info.id, f"disabled: {info.error}")

    def list_plugins(self) -> list[dict[str, Any]]:
        """For Settings: every plugin found, with enabled flag, state and error."""
        return [{"id": i.id, "name": i.name, "version": i.manifest.version if i.manifest else "",
                 "enabled": i.enabled, "state": i.state, "error": i.error} for i in self.plugins.values()]

    def failed(self) -> list[PluginInfo]:
        return [i for i in self.plugins.values() if i.state == "failed"]

    def actions_for(self, screen: str, role: str) -> list[tuple[str, ActionSpec]]:
        """Buttons to draw: (plugin id, action) for loaded plugins whose action names ``screen``."""
        out = []
        for info in self.plugins.values():
            if info.state != "enabled" or info.manifest is None:
                continue
            for action in info.manifest.actions:
                if screen in action.screens and role in action.roles and action.id in info.actions:
                    out.append((info.id, action))
        return out

    # ---- running ------------------------------------------------------------------

    @contextmanager
    def _in_action(self, name: str) -> Iterator[None]:
        previous = getattr(self._local, "action", "")
        self._local.action = name
        try:
            yield
        finally:
            self._local.action = previous

    def current_action(self) -> str:
        return getattr(self._local, "action", "") or ""

    def run_action(self, plugin_id: str, action_id: str, payload: Any = None) -> ActionResult:
        info = self.plugins.get(plugin_id)
        if info is None or info.state != "enabled":
            return ActionResult("unknown", error=f"plugin {plugin_id} is not running")
        handler = info.actions.get(action_id)
        if handler is None:
            return ActionResult("unknown", error=f"plugin {plugin_id} has no action {action_id}")
        try:
            with self._in_action(action_id):
                return ActionResult("ok", handler(payload))
        except SendDeclined as exc:
            return ActionResult("declined", error=str(exc))
        except Exception as exc:  # contained: a failing plugin is disabled, the app goes on
            self.fail(info, exc, f"action {action_id}")
            return ActionResult("error", error=info.error)

    def dispatch(self, event: str, *args: Any) -> None:
        """Call every handler of ``event``. Errors disable that plugin only."""
        for info in list(self.plugins.values()):
            if info.state != "enabled":
                continue
            for handler in list(info.handlers.get(event, [])):
                try:
                    with self._in_action(event):
                        handler(*args)
                except SendDeclined:
                    continue
                except Exception as exc:
                    self.fail(info, exc, f"event {event}")
                    break

    def start(self) -> None:
        self.discover()
        self.load_all()
        self.dispatch("on_start")

    def after_commit(self, report: Any) -> None:
        """Hand the committed changes to plugins. Never raises, so it can follow any commit."""
        try:
            self.dispatch("after_commit", changes_from_report(report))
        except Exception as exc:
            log.error("after_commit dispatch failed: %s", exc)

    # ---- jobs -----------------------------------------------------------------------

    def poll_jobs(self) -> None:
        """Ask the owning plugin about each running job (``on_job_poll``)."""
        for job in [j for j in self.jobs.values() if j.state == "running"]:
            info = self.plugins.get(job.plugin)
            if info is None or info.state != "enabled":
                continue
            for handler in list(info.handlers.get("on_job_poll", [])):
                try:
                    with self._in_action("on_job_poll"):
                        handler(job)
                except SendDeclined:
                    continue
                except Exception as exc:
                    self.fail(info, exc, "event on_job_poll")
                    job.state, job.message = "failed", info.error
                    break

    def status_bar_jobs(self) -> list[str]:
        return [f"{j.label}: {j.message or j.state}" for j in self.jobs.values() if j.state == "running"]

    # ---- audit and logs ----------------------------------------------------------------

    def audit(self, plugin: str, action: str, host: str, record_ids: Iterable[str], result: str) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "user": self.user,
                 "plugin": plugin, "action": action, "host": host, "record_ids": list(record_ids),
                 "result": result}
        line = self.scrub(json.dumps(entry, ensure_ascii=False))
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def audit_entries(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line]

    def plugin_log(self, plugin: str, text: str) -> None:
        line = self.scrub(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} [{plugin}] {text}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def skip_preview(self, plugin: str, action: str) -> None:
        self._skip_preview.add((plugin, action))

    # ---- host check ----------------------------------------------------------------------

    def allowed_hosts(self, info: PluginInfo | None) -> list[str]:
        if info is None or info.manifest is None:
            return []
        out: list[str] = []
        for entry in info.manifest.hosts:
            template = CONFIG_HOST.match(entry)
            if not template:
                out.append(entry)
                continue
            value = self.get_config(info.id, template.group(1)).strip().lower()
            if value:
                out.append(urlparse(value if "://" in value else "//" + value).netloc)
        return out


class PluginApi:
    """What a plugin gets in ``register(api)``. The only thing it may use."""

    def __init__(self, host: PluginHost, plugin_id: str, info: PluginInfo | None):
        self._host = host
        self.plugin_id = plugin_id
        self._info = info
        self.user = host.user

    # ---- registration ------------------------------------------------------------

    def action(self, action_id: str, handler: Callable[[Any], Any]) -> None:
        """Bind a handler to an action declared in the manifest."""
        assert self._info and self._info.manifest
        if self._info.manifest.action(action_id) is None:
            raise ValueError(f"action {action_id!r} is not declared in plugin.yaml")
        self._info.actions[action_id] = handler

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        assert self._info and self._info.manifest
        if event not in self._info.manifest.events:
            raise ValueError(f"event {event!r} is not declared in plugin.yaml")
        self._info.handlers.setdefault(event, []).append(handler)

    # ---- reading ---------------------------------------------------------------------

    def today(self) -> date:
        return self._host.today()

    def read(self, table: str, where: Mapping[str, Any] | Callable[[dict[str, Any]], bool] | None = None
             ) -> list[dict[str, Any]]:
        """Cached records of ``table`` as flat dicts. A copy: changing it changes nothing."""
        rows = [flatten(r) for r in self._host.store.cache_records(table)]
        if callable(where):
            return [r for r in rows if where(r)]
        if where:
            return [r for r in rows if all(r.get(k) == v for k, v in where.items())]
        return rows

    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return {t: self.read(t) for t in schema_mod.table_keys(self._host.schema)}

    def rules(self, node: str | None = None) -> rules.Analysis:
        """Section 7 results on the cache (drafts are not included)."""
        ctx = rules.Context(today=self.today(), user=self.user, node=node,
                            drafts=self._host.store.count_drafts())
        return rules.analyse(self.tables(), ctx)

    def next_id(self, table: str, prefix: str | None = None) -> str | None:
        known = validation.known_ids_from(self._host.schema, self._host.store)
        return schema_mod.next_free_id(self._host.schema, table, known.get(table, set()), prefix=prefix)

    def find_draft(self, table: str, key: str) -> Draft | None:
        return next((d for d in self._host.store.list_drafts(table) if d.key == key), None)

    def list_drafts(self, table: str) -> list[Draft]:
        return list(self._host.store.list_drafts(table))

    # ---- writing: drafts only ----------------------------------------------------------

    def _check_write(self, table: str, fields: Mapping[str, Any]) -> None:
        if self._info is not None:  # the core app (plugin id "core") is not restricted
            assert self._info.manifest
            if table not in self._info.manifest.writes:
                raise WriteNotAllowed(f"plugin {self.plugin_id} may not write {table}; add it to 'writes'")
        banned = PROTECTED_FIELDS.get(table, frozenset()) & set(fields)
        if banned:
            raise WriteNotAllowed(f"{table}.{', '.join(sorted(banned))} belongs to another system; T3 Desk never writes it")

    def _validate(self, table: str, fields: Mapping[str, Any], *, op: str, key: str | None) -> None:
        known = validation.known_ids_from(self._host.schema, self._host.store)
        issues = validation.validate_record(self._host.schema, table, fields, known_ids=known, op=op, key=key)
        if issues:
            raise DraftInvalid(table, issues)

    def draft_create(self, table: str, fields: Mapping[str, Any]) -> Draft:
        """The only way to add a record. Goes through validation and the user's Commit."""
        self._check_write(table, fields)
        id_name = schema_mod.id_field(self._host.schema, table)
        key = str(fields.get(id_name, ""))
        if self.find_draft(table, key) is not None:
            raise DraftExists(f"a draft for {table} {key} already exists")
        self._validate(table, fields, op="create", key=key)
        return self._host.store.add_draft(table, id_name, dict(fields))

    def draft_update(self, table: str, record_id: str, fields: Mapping[str, Any]) -> Draft | None:
        """Change a record. Merges into an existing draft; drops values that equal the current ones.

        Returns the draft, or None when nothing would change."""
        self._check_write(table, fields)
        store = self._host.store
        id_name = schema_mod.id_field(self._host.schema, table)
        draft = self.find_draft(table, record_id)
        if draft is not None:
            changed = {k: v for k, v in fields.items() if _norm(draft.fields.get(k)) != _norm(v)}
            if not changed:
                return None
            merged = {**draft.fields, **changed}
            self._validate(table, merged, op=draft.op, key=record_id)
            return store.update_draft(draft.id, fields=merged)
        cached = next((r for r in store.cache_records(table) if (r.get("fields") or {}).get(id_name) == record_id), None)
        if cached is None:
            raise RecordNotFound(f"{table} {record_id} is not in the cache")
        current = cached.get("fields") or {}
        changed = {k: v for k, v in fields.items() if _norm(current.get(k)) != _norm(v)}
        if not changed:
            return None
        self._validate(table, changed, op="update", key=record_id)
        return store.add_draft(table, id_name, changed, op="update", record_id=cached["id"], key=record_id,
                               base_modified=cached.get("lastModifiedTime"),
                               base_fields={k: current.get(k) for k in changed})

    def draft_discard(self, table: str, key: str) -> bool:
        """Drop an unsent local draft (for example a task that turned out to exist already)."""
        if self._info is not None:
            self._check_write(table, {})
        draft = self.find_draft(table, key)
        if draft is None:
            return False
        self._host.store.remove_draft(draft.id)
        return True

    # ---- config, secrets, messages -------------------------------------------------------

    def config(self, key: str) -> str:
        return self._host.get_config(self.plugin_id, key)

    def secret(self, key: str) -> str | None:
        return self._host.get_secret(self.plugin_id, key)

    def notify(self, text: str) -> None:
        self._host.notifications.append((self.plugin_id, self._host.scrub(text)))

    def log(self, *parts: Any) -> None:
        self._host.plugin_log(self.plugin_id, " ".join(str(p) for p in parts))

    # ---- jobs --------------------------------------------------------------------------------

    def job_start(self, label: str, *, ref: str = "", data: Mapping[str, Any] | None = None) -> int:
        host = self._host
        with host._lock:
            host._job_seq += 1
            job = Job(host._job_seq, self.plugin_id, label, ref=ref, data=dict(data or {}))
            host.jobs[job.id] = job
        return job.id

    def job_update(self, job_id: int, *, state: str | None = None, message: str | None = None,
                   result: Mapping[str, Any] | None = None) -> Job:
        job = self._host.jobs[job_id]
        if job.plugin != self.plugin_id:
            raise WriteNotAllowed("a plugin may only update its own jobs")
        if state is not None:
            if state not in ("running", "done", "failed"):
                raise ValueError(f"bad job state {state!r}")
            job.state = state
        if message is not None:
            job.message = self._host.scrub(message)
        if result is not None:
            job.result = dict(result)
        return job

    # ---- sending ---------------------------------------------------------------------------------

    def check_host(self, url: str) -> str:
        """Return the URL's host, or raise HostNotAllowed. Call before any other network use."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise HostNotAllowed(f"{self.plugin_id}: refused {url.split('?')[0]!r}: not a plain http(s) URL")
        host = parsed.hostname.lower()
        for entry in self._host.allowed_hosts(self._info):
            name, _, port = entry.partition(":")
            if name == host and (not port or port == str(parsed.port or "")):
                return f"{host}:{parsed.port}" if parsed.port else host
        self._host.audit(self.plugin_id, self._host.current_action(), host, [], "refused: host not in manifest")
        raise HostNotAllowed(f"{self.plugin_id}: host {host!r} is not in the plugin manifest")

    def confirm_send(self, target: str, payload: Any, *, method: str = "CALL",
                     record_ids: Iterable[str] = ()) -> None:
        """Show the exact payload and target; raise SendDeclined unless the user confirms."""
        host = self._host
        action = host.current_action()
        if (self.plugin_id, action) in host._skip_preview:
            return
        preview = SendPreview(self.plugin_id, action, method, target, target, payload, tuple(record_ids))
        answer = host.confirm(preview) if host.confirm else False
        if not answer:
            host.audit(self.plugin_id, action, target, record_ids, "declined by user")
            raise SendDeclined("the user did not confirm the preview")
        if answer == SESSION:
            host.skip_preview(self.plugin_id, action)

    def audit_send(self, target: str, result: str, record_ids: Iterable[str] = ()) -> None:
        self._host.audit(self.plugin_id, self._host.current_action(), target, record_ids, result)

    def http(self, method: str, url: str, json: Any = None, *, headers: Mapping[str, str] | None = None,
             record_ids: Iterable[str] = ()) -> HttpReply:
        """HTTP with a timeout, refused unless the host is in the manifest.

        A call that carries a body shows the preview first. Headers (tokens) are never previewed,
        logged or audited."""
        target = self.check_host(url)
        ids = tuple(record_ids)
        method = method.upper()
        if json is not None:
            self.confirm_send(target, json, method=method, record_ids=ids)
            preview_url = url.split("?")[0]
            # the preview above carries the host; also keep the full path in the audit
            target_for_audit = target + urlparse(preview_url).path
        else:
            target_for_audit = target
        host = self._host
        try:
            with httpx.Client(timeout=host.timeout, transport=host._transport, trust_env=False) as client:
                response = client.request(method, url, json=json, headers=dict(headers or {}))
        except httpx.HTTPError as exc:
            message = host.scrub(f"{type(exc).__name__}: {exc}")
            self.audit_send(target_for_audit, f"network error: {message}", ids)
            raise PluginHttpError(f"{method} {target} failed: {message}. Check the address and that the server runs.") from None
        self.audit_send(target_for_audit, f"HTTP {response.status_code}", ids)
        return HttpReply(response.status_code, response.text)
