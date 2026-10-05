# hermes_skill

Runs the mapped Hermes skill for "Tạo RFQ" and "Tạo RFP", keeps the run id in
`rfq.ma_tac_vu_ngoai`, polls until the run ends, then stores the returned link (or text) in
`rfq.link_tai_lieu` and sets the draft to `Đã tạo`. The user commits.

## What follows the documentation (`docs/reference/hermes-api-server.md`)

- `POST /v1/runs` with `{"input", "instructions", "session_id"}`. `session_id` is `t3desk-<ma_rfq>`.
- Header `Idempotency-Key: t3desk-<ma_rfq>` (so a retried start does not create a second run).
- `Authorization: Bearer <API_SERVER_KEY>`; the key is a secret config value, never previewed or logged.
- `GET /v1/runs/{run_id}` is polled (event `on_job_poll`) until the run ends.
- HTTP 429 (max concurrent runs): on start the user is notified "Hermes is busy, retry later", the action
  returns `{"retry_later": true}` (the plugin stays enabled) and the draft stays `Nháp`; while polling it is treated as "still running".
- There is no skill parameter, so the skill name is written into `input` and `instructions`, with the
  RFQ/RFP payload JSON embedded in `input`. The skill is asked to reply with
  `{"link": "...", "text": "..."}`; the link/text is parsed from `output` (JSON, else the first URL,
  else the whole text).
- The payload never contains another vendor's price, the budget or scores (guard in `t3desk.rfq`).
  The preview shows the exact request body and host before anything is sent. Only the host in
  `base_url` is allowed (`{config:base_url}` in `plugin.yaml`).
- `run_skill` in `plugin.py` is the only function that knows the wire format.

## Still UNVERIFIED (not in the documentation; nothing has run against a real Hermes)

- The exact `status` values of `GET /v1/runs/{id}`. `plugin.py` assumes
  `completed/succeeded/success/done` for finished and `failed/cancelled/canceled/stopped/error` for
  ended-without-result (`DONE_STATUSES`, `FAILED_STATUSES`); anything else counts as running.
- Where Hermes stores generated documents. We only ask the skill to return a link or text in `output`.
- The real skill names. Config defaults `rfq` and `rfp` are placeholders (`GET /v1/skills` lists them).
- Whether the skill obeys the "reply with JSON" instruction; the parser falls back to a URL or raw text.

Config: `base_url`, `token` (secret), `skill_tao_rfq`, `skill_tao_rfp`.
Data leaving the LAN: payloads go to Hermes, which may be outside the NAS (open question, requirements 13).
