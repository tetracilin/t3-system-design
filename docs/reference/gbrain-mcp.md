# gbrain MCP server (reference extract)

Sources (fetched 2026-10-05 via a summarising fetch tool; confirm against the repo):
- https://github.com/garrytan/gbrain/blob/master/docs/mcp/README.md
- .../docs/mcp/DEPLOY.md, .../docs/mcp/TOOL_REFERENCE.md

Transport and auth:
- Remote HTTP MCP server; protected resource path `/mcp` (RFC 9728 metadata at `/.well-known/oauth-protected-resource/mcp`). Example URL shape: `https://<machine>.<tailnet>.ts.net/mcp`. A local stdio mode also exists.
- Auth: OAuth 2.1 (auth code + PKCE, client credentials for machine clients, refresh rotation) or legacy bearer tokens made with `gbrain auth create "<name>" [--scopes read,write]`. Without `--scopes` a bearer token gets read+write+admin: create read-only tokens for T3 Desk (`--scopes read`).
- Client config example: URL `https://<host>/mcp` with header `Authorization: Bearer <token>`.
- Owner/dashboard administration is separate from MCP scopes; T3 Desk never needs it.

Tools relevant to T3 Desk (read-only use):
- `entity` (required `name`): inspect ONE known person/company/project card, zero LLM calls; returns `found` and suggestions.
- `search` (hybrid vector+keyword): exact names/tokens. `query`: hybrid with expansion. `recall`: saved facts by entity or text. `synthesize`: cross-page answer with citations (uses an LLM).
- `get_page` (required `slug`; optional `fuzzy`, `include_content`).
- `whoami`: introspect identity (good connection test).
- Write tools exist (`put_page`, `capture`, `remember`, ...) with a `request_id` / `get_write_request` receipt flow. T3 Desk must NOT call them.
- No RFQ/RFP tool is documented. `submit_agent` / `get_agent_job` exist but their arguments are not documented here: UNVERIFIED, do not ship a mapping.
- Exact parameter names for `search`/`query` were not captured: UNVERIFIED until `tools/list` is read from the live server (the Settings screen lists the server's tools).
