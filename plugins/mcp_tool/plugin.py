"""MCP client plugin for gbrain (read-only). ``mcp`` is imported only inside ``open_session``.

gbrain is reached as a REMOTE HTTP MCP server: config ``url`` (https://<host>/mcp) plus a secret
bearer token sent as ``Authorization: Bearer <token>``. The host allow-list comes from the url
host (manifest ``{config:url}``). A stdio command stays available as the alternative transport.

``mappings`` maps each action to a tool and an argument template (``{{path}}`` is replaced from
the action payload). A mapping may instead hold ``any_of``: a list of such options; the first
option whose arguments are all non-empty is used, and ``fallback`` names an option to try when
the first call finds nothing. Results are shown to the user only. Nothing is written, not even a
draft, and WRITE_TOOLS can never be called (checked in code, whatever the mappings say).

UNVERIFIED: the exact argument names of ``search`` and ``query`` (assumed ``query``) and the shape
of any response (the ``found`` flag of ``entity`` is read only if the text is JSON). Read the real
``tools/list`` from the Settings screen and adjust ``mappings``. See docs/reference/gbrain-mcp.md.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlparse

# gbrain write tools (docs/reference/gbrain-mcp.md). T3 Desk must never call them.
WRITE_TOOLS = frozenset({
    "put_page", "edit_page", "capture", "remember", "forget", "add_timeline_entry", "submit_agent",
})
WRITE_PREFIXES = ("cancel_",)

_NAME_PATHS = ("vendor", "nha_cung_cap", "items.0.hang", "hang", "items.0.model", "model")
_QUERY = "{{vendor}} {{nha_cung_cap}} {{items.0.hang}} {{hang}} {{items.0.model}} {{model}}"
_SEARCH = {"tool": "search", "args": {"query": _QUERY}}
DEFAULT_MAPPINGS: dict[str, dict[str, Any]] = {
    # entity(name) for the vendor, else the brand, else the model of the selected candidate;
    # search(query) when there is no name or entity reports found=false.
    "tra_cuu_boi_canh": {
        "any_of": [{"tool": "entity", "args": {"name": "{{%s}}" % p}} for p in _NAME_PATHS] + [_SEARCH],
        "fallback": _SEARCH,
    },
    "kiem_tra_ket_noi": {"tool": "whoami", "args": {}},
}
_WHOLE = re.compile(r"^\{\{\s*([^{}]*?)\s*\}\}$")
_PART = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def is_write_tool(tool: str) -> bool:
    name = tool.strip().lower()
    return name in WRITE_TOOLS or name.startswith(WRITE_PREFIXES)


def assert_read_only(tool: str) -> None:
    if is_write_tool(tool):
        raise PermissionError(f"mcp_tool: {tool} is a write tool; T3 Desk never calls gbrain write tools")


def lookup(payload: Any, path: str) -> Any:
    """``a.b.0`` -> payload['a']['b'][0]; ``.`` is the whole payload; missing -> None."""
    if path in ("", "."):
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _text_of(payload: Any, match: re.Match[str]) -> str:
    value = lookup(payload, match.group(1))
    return "" if value is None else str(value)


def render_template(template: Any, payload: Any) -> Any:
    """Fill ``{{path}}`` placeholders. A string that is only a placeholder keeps the value's type."""
    if isinstance(template, dict):
        return {k: render_template(v, payload) for k, v in template.items()}
    if isinstance(template, list):
        return [render_template(v, payload) for v in template]
    if not isinstance(template, str):
        return template
    whole = _WHOLE.match(template)
    if whole:
        return lookup(payload, whole.group(1))
    return " ".join(_PART.sub(lambda m: _text_of(payload, m), template).split())


def load_mappings(api: Any) -> dict[str, dict[str, Any]]:
    text = api.config("mappings").strip()
    merged = {k: dict(v) for k, v in DEFAULT_MAPPINGS.items()}
    if text:
        merged.update(json.loads(text))
    return merged


def _filled(arguments: dict[str, Any]) -> bool:
    return all(v not in (None, "", [], {}) for v in arguments.values())


def choose_call(mapping: dict[str, Any], payload: Any) -> tuple[str, dict[str, Any]]:
    """Return (tool, rendered arguments) for the mapping, or raise ValueError."""
    options = mapping.get("any_of") or [mapping]
    for option in options:
        tool = str(option.get("tool") or "")
        if not tool:
            continue
        arguments = render_template(option.get("args") or {}, payload)
        if _filled(arguments):
            return tool, arguments
    raise ValueError("mcp_tool: nothing to look up; select a candidate with a vendor, brand or model")


def _is_url(api: Any) -> bool:
    return api.config("transport").strip().lower() == "url"


def target_of(api: Any) -> str:
    """Where the call goes, for the preview and the audit log. Checks the host allow-list for URLs."""
    if _is_url(api):
        url = api.config("url").strip()
        target = api.check_host(url)
        parsed = urlparse(url)
        if parsed.scheme != "https" and (parsed.hostname or "") not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("mcp_tool: the bearer token is sent only over https (http is allowed for localhost)")
        return target
    command = api.config("command").strip()
    if not command:
        raise ValueError("mcp_tool: set the server url (remote gbrain) or a stdio command")
    return "stdio:" + command


def auth_headers(api: Any) -> dict[str, str]:
    token = (api.secret("token") or "").strip()
    if not token:
        raise ValueError("mcp_tool: set the bearer token in Settings (gbrain auth create --scopes read)")
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def open_session(api: Any) -> AsyncIterator[Any]:
    """Yield an initialised MCP ClientSession. The only place that imports ``mcp``."""
    from mcp import ClientSession, StdioServerParameters  # imported only when an action runs

    if _is_url(api):
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        async with create_mcp_http_client(headers=auth_headers(api)) as http_client:
            async with streamable_http_client(api.config("url").strip(), http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        return
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=api.config("command").strip(),
                                   args=shlex.split(api.config("args") or ""))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def result_text(result: Any) -> str:
    parts = [getattr(c, "text", "") for c in (getattr(result, "content", None) or [])]
    return "\n".join(p for p in parts if p) or str(result)


async def _call(api: Any, tool: str, arguments: dict[str, Any]) -> str:
    assert_read_only(tool)  # last line of defence, right before the wire
    async with open_session(api) as session:
        return result_text(await session.call_tool(tool, arguments))


async def _list(api: Any) -> list[dict[str, str]]:
    async with open_session(api) as session:
        listing = await session.list_tools()
        return [{"name": t.name, "description": getattr(t, "description", "") or ""} for t in listing.tools]


def found_nothing(text: str) -> bool:
    """UNVERIFIED shape: True only when the text is JSON with ``found`` false."""
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("found") is False


def _send(api: Any, target: str, tool: str, arguments: dict[str, Any], ids: list[str]) -> str:
    assert_read_only(tool)
    api.confirm_send(target, {"tool": tool, "arguments": arguments}, method="MCP")
    try:
        text = asyncio.run(_call(api, tool, arguments))
    except Exception as exc:
        api.audit_send(target, f"error: {type(exc).__name__}", ids)
        raise
    api.audit_send(target, "ok", ids)
    return text


def run_mapped(api: Any, action: str, payload: Any) -> str:
    mapping = load_mappings(api).get(action) or {}
    if not (mapping.get("any_of") or mapping.get("tool")):
        raise ValueError(f"mcp_tool: no tool is mapped to {action}; map one in Settings")
    tool, arguments = choose_call(mapping, payload)
    assert_read_only(tool)
    target = target_of(api)
    ids = [str(payload.get("ma_rfq"))] if isinstance(payload, dict) and payload.get("ma_rfq") else []
    text = _send(api, target, tool, arguments, ids)
    fallback = mapping.get("fallback")
    if fallback and tool != fallback.get("tool") and found_nothing(text):
        f_tool, f_args = choose_call(fallback, payload)
        text = _send(api, target, f_tool, f_args, ids)
    api.notify(text)
    return text


def list_server_tools(api: Any, _payload: Any = None) -> list[dict[str, str]]:
    target_of(api)
    tools = asyncio.run(_list(api))
    api.notify("; ".join(t["name"] for t in tools) or "(no tools)")
    return tools


def register(api: Any) -> None:
    for action in ("tra_cuu_boi_canh", "kiem_tra_ket_noi"):
        api.action(action, lambda payload, a=action: run_mapped(api, a, payload))
    api.action("liet_ke_cong_cu", lambda payload: list_server_tools(api, payload))
