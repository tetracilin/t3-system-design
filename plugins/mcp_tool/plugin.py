"""Generic MCP client plugin. ``mcp`` is imported only inside ``open_session``, when an action runs.

Config chooses the transport (a stdio command or a URL). ``mappings`` maps each action to a tool
name and an argument template; ``{{path}}`` in a template is replaced from the action payload.
Results are shown to the user (notify and return value). Nothing is written, not even a draft.

UNVERIFIED: the shipped gbrain mappings (DEFAULT_MAPPINGS) are guesses. There is no gbrain
reference in docs/reference/. Use the "list tools" action to see what the server really offers
and set ``mappings`` to match.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# UNVERIFIED gbrain mappings. An empty tool name means "gbrain offers nothing for this action".
DEFAULT_MAPPINGS: dict[str, dict[str, Any]] = {
    "tra_cuu_boi_canh": {"tool": "query", "args": {"query": "{{items.0.hang}} {{items.0.model}} {{vendor}}"}},
    "tao_rfq": {"tool": "", "args": {"payload": "{{.}}"}},
    "tao_rfp": {"tool": "", "args": {"payload": "{{.}}"}},
}
_WHOLE = re.compile(r"^\{\{\s*([^{}]*?)\s*\}\}$")
_PART = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


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


def target_of(api: Any) -> str:
    """Where the call goes, for the preview and the audit log. Checks the host allow-list for URLs."""
    if api.config("transport").strip().lower() == "url":
        return api.check_host(api.config("url").strip())
    command = api.config("command").strip()
    if not command:
        raise ValueError("mcp_tool: set the server command (stdio) or switch the transport to url")
    return "stdio:" + command


@asynccontextmanager
async def open_session(api: Any) -> AsyncIterator[Any]:
    """Yield an initialised MCP ClientSession. The only place that imports ``mcp``."""
    from mcp import ClientSession, StdioServerParameters  # imported only when an action runs

    if api.config("transport").strip().lower() == "url":
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(api.config("url").strip()) as (read, write, _close):
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
    async with open_session(api) as session:
        return result_text(await session.call_tool(tool, arguments))


async def _list(api: Any) -> list[dict[str, str]]:
    async with open_session(api) as session:
        listing = await session.list_tools()
        return [{"name": t.name, "description": getattr(t, "description", "") or ""} for t in listing.tools]


def run_mapped(api: Any, action: str, payload: Any) -> str:
    mapping = load_mappings(api).get(action) or {}
    tool = str(mapping.get("tool") or "")
    if not tool:
        raise ValueError(f"mcp_tool: no tool is mapped to {action}; map one in Settings")
    arguments = render_template(mapping.get("args") or {}, payload)
    target = target_of(api)
    api.confirm_send(target, {"tool": tool, "arguments": arguments}, method="MCP")
    ids = [str(payload.get("ma_rfq"))] if isinstance(payload, dict) and payload.get("ma_rfq") else []
    try:
        text = asyncio.run(_call(api, tool, arguments))
    except Exception as exc:
        api.audit_send(target, f"error: {type(exc).__name__}", ids)
        raise
    api.audit_send(target, "ok", ids)
    api.notify(text)
    return text


def list_server_tools(api: Any, _payload: Any = None) -> list[dict[str, str]]:
    target_of(api)
    tools = asyncio.run(_list(api))
    api.notify("; ".join(t["name"] for t in tools) or "(no tools)")
    return tools


def register(api: Any) -> None:
    for action in ("tra_cuu_boi_canh", "tao_rfq", "tao_rfp"):
        api.action(action, lambda payload, a=action: run_mapped(api, a, payload))
    api.action("liet_ke_cong_cu", lambda payload: list_server_tools(api, payload))
