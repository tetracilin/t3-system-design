# mcp_tool

MCP client for gbrain, read-only. The `mcp` package is imported only inside `open_session()` in
`plugin.py`, when an action runs, so the core app and a disabled plugin never need it
(`pip install -e ".[mcp]"`).

## Connect

- Remote (default, `transport = url`): `url` = `https://<host>/mcp`, `token` = a gbrain bearer
  token (stored as a secret, sent as `Authorization: Bearer <token>`). Create it read-only:
  `gbrain auth create "t3desk" --scopes read`. Plain `http` is accepted only for localhost.
  The host allow-list is derived from the `url` host; any other host is refused.
- Alternative (`transport = stdio`): `command` and `args` start a local gbrain MCP server.

## Actions

- "Tra cứu bối cảnh": tool `entity` with `name` = vendor (`nha_cung_cap`), else brand (`hang`),
  else model of the selected candidate; falls back to `search` with a `query` string when there is
  no name or `entity` reports `found: false`.
- "Kiểm tra kết nối gbrain": tool `whoami`.
- "Liệt kê công cụ của máy chủ": `tools/list`, shown in Settings. Use it to set `mappings`.

`mappings` is JSON: `{"action": {"tool": "<tool>", "args": {"k": "{{payload.path}}"}}}`, or
`{"any_of": [...], "fallback": {...}}`. Every call shows its tool and arguments for confirmation
and is written to the audit log. Results are shown to the user only; nothing is drafted.

## Read-only guarantee

`WRITE_TOOLS` (`put_page`, `edit_page`, `capture`, `remember`, `forget`, `add_timeline_entry`,
`submit_agent`) and any `cancel_*` tool are refused in code, before the preview and again before
the wire, whatever `mappings` says. There is no RFQ/RFP mapping: gbrain has no such tool.

## UNVERIFIED

Nothing was run against a real gbrain server (tested against a fake HTTP MCP server). Not
documented, so assumed: the argument name `query` of `search`, and response shapes (the `found`
flag of `entity` is read only when the reply text is JSON). Confirm with `tools/list`.
