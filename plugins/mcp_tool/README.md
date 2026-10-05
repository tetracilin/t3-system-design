# mcp_tool

Generic MCP client. The `mcp` package is imported only inside `open_session()` in `plugin.py`,
when an action actually runs, so the core app and a disabled plugin never need it
(`pip install mcp` or `pip install -e ".[mcp]"`).

Config: `transport` (`stdio` or `url`), `command` and `args` (stdio) or `url`, and `mappings`.
`mappings` is JSON: `{"action": {"tool": "<server tool>", "args": {"k": "{{payload.path}}"}}}`.
Placeholders such as `{{items.0.hang}}` read the action payload; a value that is only a
placeholder keeps its type. The action "Liệt kê công cụ của máy chủ" shows what the server
reports so you can fill `mappings`.

Every call shows its tool and arguments for confirmation first and is written to the audit log.
For `url` the host must match `{config:url}`. Results are shown only; nothing is drafted.

## UNVERIFIED

The gbrain mappings in `DEFAULT_MAPPINGS` ("Tra cứu bối cảnh" -> tool `query`; "Tạo RFQ / RFP" ->
no tool) are guesses. No gbrain reference exists in `docs/reference/`, and nothing was run
against a real gbrain server. The MCP client code is tested only against a fake session.
