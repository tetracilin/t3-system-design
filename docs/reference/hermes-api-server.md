# Hermes API server (reference extract)

Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server (fetched 2026-10-05, summarised by a fetch tool, so confirm against the live page and the deployed Hermes version).

- Base URL default `http://127.0.0.1:8642/v1`; port/host via `API_SERVER_PORT`, `API_SERVER_HOST`. Server is off unless `API_SERVER_ENABLED=true`.
- Auth: `Authorization: Bearer <API_SERVER_KEY>`.
- Health: `GET /health` -> `{"status":"ok"}`. Capabilities: `GET /v1/capabilities`.
- Skills discovery (read-only): `GET /v1/skills` -> `[{"name","description","category"}]`.
- Runs API (long-running, pollable):
  - `POST /v1/runs` body `{"input": str, "session_id": optional str, "instructions": optional str}`, optional header `Idempotency-Key` (1-255 chars). Returns `{"run_id": "...", "status": "started"}`.
  - `GET /v1/runs/{run_id}` -> includes `status`, `output`, `usage`, `runtime`.
  - `GET /v1/runs/{run_id}/events` SSE: `tool.started`, `tool.completed`, `message.interim`, `run.completed`, `run.failed`, `run.cancelled`.
  - `POST /v1/runs/{run_id}/stop` -> `{"status":"stopping"}`.
  - `POST /v1/runs/{run_id}/approval` resolves an approval gate.
- Concurrency cap `max_concurrent_runs` (default 10); beyond it HTTP 429 `Too many concurrent runs (max N)`.
- There is NO documented "run skill X" parameter on `/v1/runs`. A skill is invoked by naming it in `input`/`instructions`; `/api/jobs` accepts `skills` but is for scheduled jobs.
- Not documented: exact `status` values on `GET /v1/runs/{id}` and where generated documents are stored. Treat as UNVERIFIED.
