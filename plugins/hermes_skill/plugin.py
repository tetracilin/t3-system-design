"""Hermes skill plugin: runs the RFQ / RFP skill in Hermes for a payload built by t3desk.rfq.

UNVERIFIED: there is no Hermes API reference in docs/reference/. The HTTP calls in
``run_skill`` are an assumption, written against tests/fake_hermes.py. Replace that one function
when the real reference is supplied; nothing else in this plugin knows the wire format.
"""

from __future__ import annotations

from typing import Any

PLUGIN_ID = "hermes_skill"
STATUS_CREATING = "Đang tạo"  # rfq.trang_thai values (schema choices)
STATUS_CREATED = "Đã tạo"
STATUS_DRAFT = "Nháp"

RUN_PATH = "/v1/skills/{skill}/runs"  # UNVERIFIED
POLL_PATH = "/v1/runs/{ref}"  # UNVERIFIED


def run_skill(api: Any, skill: str, payload: dict[str, Any] | None = None, run_ref: str | None = None
              ) -> dict[str, Any]:
    """The one function that knows the Hermes wire format. UNVERIFIED.

    With ``payload``: start the skill and return ``{"ref", "state": "running"}``.
    With ``run_ref``: ask about a run and return ``{"ref", "state", "link", "text", "error"}``
    where state is running, done or failed."""
    base = api.config("base_url").rstrip("/")
    headers = {"Authorization": f"Bearer {api.secret('token') or ''}"}
    if payload is not None:
        ids = [payload.get("ma_rfq", "")] + [i.get("ma_uv", "") for i in payload.get("items", [])]
        reply = api.http("POST", base + RUN_PATH.format(skill=skill), payload, headers=headers,
                         record_ids=[i for i in ids if i])
        if not reply.ok:
            raise RuntimeError(f"Hermes refused the run (HTTP {reply.status}): {reply.text[:200]}")
        return {"ref": str(reply.json()["run_id"]), "state": "running"}
    reply = api.http("GET", base + POLL_PATH.format(ref=run_ref), headers=headers)
    if not reply.ok:
        raise RuntimeError(f"Hermes run {run_ref} lookup failed (HTTP {reply.status}): {reply.text[:200]}")
    body = reply.json()
    state = {"succeeded": "done", "failed": "failed"}.get(str(body.get("state")), "running")
    return {"ref": run_ref, "state": state, "link": body.get("link") or "", "text": body.get("text") or "",
            "error": body.get("error") or ""}


def _start(api: Any, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    skill = api.config("skill_" + action)
    started = run_skill(api, skill, payload=payload)
    ma_rfq = payload["ma_rfq"]
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
