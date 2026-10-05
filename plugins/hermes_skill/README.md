# hermes_skill (UNVERIFIED)

Runs the mapped Hermes skill for "Tạo RFQ" and "Tạo RFP", keeps the run reference in
`rfq.ma_tac_vu_ngoai`, polls until the run ends, then stores the returned link (or text) in
`rfq.link_tai_lieu` and sets the draft to `Đã tạo`. The user commits.

**UNVERIFIED.** No Hermes API reference exists in `docs/reference/`. The two HTTP calls in
`run_skill` (`plugin.py`) are invented to match `tests/fake_hermes.py`. Nothing here has run
against a real Hermes. When the reference arrives, rewrite `run_skill` only; keep its contract
(start with `payload`, poll with `run_ref`).

Config: `base_url`, `token` (secret), `skill_tao_rfq`, `skill_tao_rfp` (defaults are placeholders).
The host list in `plugin.yaml` is `{config:base_url}`, so only the configured Hermes address is allowed.
Data leaving the LAN: payloads go to Hermes, which may be outside the NAS (open question, requirements 13).
