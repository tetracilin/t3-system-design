"""Hermes skill plugin: runs the RFQ / RFP skill in Hermes for a payload built by t3desk.rfq.

Follows the Runs API in docs/reference/hermes-api-server.md: ``POST /v1/runs`` with
``{"input", "instructions", "session_id"}`` and an ``Idempotency-Key`` header, then
``GET /v1/runs/{run_id}`` until the run ends. There is no skill parameter, so the skill is
requested by name inside ``input`` / ``instructions`` with the payload JSON embedded.

Still UNVERIFIED (not documented): the exact ``status`` values of ``GET /v1/runs/{id}``
(see DONE_STATUSES / FAILED_STATUSES), where Hermes stores generated documents (we ask the
skill to return a link or text in ``output``), and the real skill names (config defaults).
"""

from __future__ import annotations

import json
import re
from typing import Any

PLUGIN_ID = "hermes_skill"
STATUS_CREATING = "Đang tạo"  # rfq.trang_thai values (schema choices)
STATUS_CREATED = "Đã tạo"
STATUS_DRAFT = "Nháp"

RUN_PATH = "/v1/runs"
POLL_PATH = "/v1/runs/{ref}"
# UNVERIFIED: the docs list events run.completed / run.failed / run.cancelled but not the status
# strings of GET /v1/runs/{id}. Anything not listed here counts as still running.
DONE_STATUSES = {"completed", "succeeded", "success", "done"}
FAILED_STATUSES = {"failed", "cancelled", "canceled", "stopped", "error"}

_URL = re.compile(r"https?://[^\s<>\"')\]]+")


class HermesBusy(RuntimeError):
    """HTTP 429: Hermes is at max_concurrent_runs. Nothing was started; retry later."""


def build_request(skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Body for POST /v1/runs. The skill is named in the text; the RFQ/RFP payload is embedded."""
    ma_rfq = str(payload.get("ma_rfq", ""))
    return {
        "input": (f'Run the Hermes skill "{skill}" for the request below. Use only the data in the '
                  f"payload JSON.\n\nPayload JSON:\n{json.dumps(payload, ensure_ascii=False)}"),
        "instructions": (f'Use the skill named "{skill}". Return only a JSON object '
                         '{"link": "<URL of the created document>", "text": "<document text if there is no link>"}.'),
        "session_id": f"t3desk-{ma_rfq}",
    }


def parse_output(output: Any) -> dict[str, str]:
    """Pull the document link / text out of a run's ``output``. Output format is UNVERIFIED."""
    if isinstance(output, dict):
        return {"link": str(output.get("link") or ""), "text": str(output.get("text") or "")}
    raw = str(output or "").strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return {"link": str(data.get("link") or ""), "text": str(data.get("text") or "")}
    found = _URL.search(raw)
    return {"link": found.group(0) if found else "", "text": raw}


def run_skill(api: Any, skill: str, payload: dict[str, Any] | None = None, run_ref: str | None = None
              ) -> dict[str, Any]:
    """The one function that knows the Hermes wire format.

    With ``payload``: start the skill and return ``{"ref", "state": "running"}``; HTTP 429 raises
    HermesBusy. With ``run_ref``: ask about a run and return ``{"ref", "state", "link", "text",
    "error"}`` where state is running, done or failed (HTTP 429 while polling means running)."""
    base = api.config("base_url").rstrip("/")
    headers = {"Authorization": f"Bearer {api.secret('token') or ''}"}
    if payload is not None:
        headers["Idempotency-Key"] = f"t3desk-{payload.get('ma_rfq', '')}"[:255]
        ids = [payload.get("ma_rfq", "")] + [i.get("ma_uv", "") for i in payload.get("items", [])]
        reply = api.http("POST", base + RUN_PATH, build_request(skill, payload), headers=headers,
                         record_ids=[i for i in ids if i])
        if reply.status == 429:
            raise HermesBusy(f"Hermes is busy (HTTP 429): {reply.text[:200]}. Retry in a few minutes.")
        if not reply.ok:
            raise RuntimeError(f"Hermes refused the run (HTTP {reply.status}): {reply.text[:200]}")
        return {"ref": str(reply.json()["run_id"]), "state": "running"}
    reply = api.http("GET", base + POLL_PATH.format(ref=run_ref), headers=headers)
    if reply.status == 429:
        return {"ref": run_ref, "state": "running", "link": "", "text": "", "error": ""}
    if not reply.ok:
        raise RuntimeError(f"Hermes run {run_ref} lookup failed (HTTP {reply.status}): {reply.text[:200]}")
    body = reply.json()
    status = str(body.get("status") or "").lower()
    if status in FAILED_STATUSES:
        error = str(body.get("error") or body.get("output") or status)
        return {"ref": run_ref, "state": "failed", "link": "", "text": "", "error": error}
    if status in DONE_STATUSES:
        return {"ref": run_ref, "state": "done", "error": "", **parse_output(body.get("output"))}
    return {"ref": run_ref, "state": "running", "link": "", "text": "", "error": ""}


def _start(api: Any, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    skill = api.config("skill_" + action)
    ma_rfq = payload["ma_rfq"]
    try:
        started = run_skill(api, skill, payload=payload)
    except HermesBusy as exc:  # not a plugin fault: tell the user, leave the draft in Nháp
        api.notify(f"{ma_rfq}: {exc}")
        return {"retry_later": True, "error": str(exc)}
    api.draft_update("rfq", ma_rfq, {"trang_thai": STATUS_CREATING, "plugin": PLUGIN_ID,
                                      "ma_tac_vu_ngoai": started["ref"]})
    job = api.job_start(f"{ma_rfq} ({skill})", ref=started["ref"], data={"ma_rfq": ma_rfq, "skill": skill})
    return {"ref": started["ref"], "job": job}


def _poll(api: Any, job: Any) -> None:
    ma_rfq = job.data["ma_rfq"]
    reply = run_skill(api, job.data["skill"], run_ref=job.ref)
    if reply["state"] == "running":
        return
    if reply["state"] == "failed":
        api.draft_update("rfq", ma_rfq, {"trang_thai": STATUS_DRAFT, "ghi_chu": f"Hermes: {reply['error']}"})
        api.job_update(job.id, state="failed", message=reply["error"] or "failed")
        api.notify(f"{ma_rfq}: Hermes run failed: {reply['error']}")
        return
    document = reply["link"] or reply["text"]
    api.draft_update("rfq", ma_rfq, {"trang_thai": STATUS_CREATED, "link_tai_lieu": document})
    api.job_update(job.id, state="done", message="done", result={"link": document})
    api.notify(f"{ma_rfq}: document ready; commit to save it")


def register(api: Any) -> None:
    api.action("tao_rfq", lambda payload: _start(api, "tao_rfq", payload))
    api.action("tao_rfp", lambda payload: _start(api, "tao_rfp", payload))
    api.on("on_job_poll", lambda job: _poll(api, job))
