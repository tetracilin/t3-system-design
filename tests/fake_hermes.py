"""In-process fake Hermes server for the hermes_skill plugin tests.

UNVERIFIED: the wire format here is invented, because no Hermes API reference exists. It mirrors
``run_skill`` in plugins/hermes_skill/plugin.py. ``FakeHermes.run_skill`` is the single function
that handles both starting a skill and asking about a run.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "hermes-test-token"


class FakeHermes:
    def __init__(self, *, polls_until_done: int = 2, link: str = "http://nas.invalid/docs/RFQ.docx",
                 fail: bool = False, token: str = TOKEN):
        self.polls_until_done = polls_until_done
        self.link = link
        self.fail = fail
        self.token = token
        self.requests: list[dict[str, Any]] = []  # what arrived: method, path, body (no headers kept)
        self.runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> FakeHermes:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeHermes:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def run_skill(self, skill: str, payload: dict[str, Any] | None = None, run_ref: str | None = None
                  ) -> dict[str, Any]:
        """Start ``skill`` with ``payload``, or report on ``run_ref`` (each report counts as a poll)."""
        with self._lock:
            if payload is not None:
                ref = f"run-{len(self.runs) + 1:04d}"
                self.runs[ref] = {"skill": skill, "payload": payload, "polls": 0}
                return {"run_id": ref}
            run = self.runs.get(run_ref or "")
            if run is None:
                return {"error": "unknown run"}
            run["polls"] += 1
            if run["polls"] < self.polls_until_done:
                return {"state": "running"}
            if self.fail:
                return {"state": "failed", "error": "skill crashed"}
            return {"state": "succeeded", "link": self.link}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                fake.requests.append({"method": method, "path": self.path, "body": body})
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    return self._reply(401, {"error": "bad token"})
                parts = self.path.strip("/").split("/")
                if method == "POST" and len(parts) == 4 and parts[:2] == ["v1", "skills"] and parts[3] == "runs":
                    return self._reply(200, fake.run_skill(parts[2], payload=body or {}))
                if method == "GET" and len(parts) == 3 and parts[:2] == ["v1", "runs"]:
                    return self._reply(200, fake.run_skill("", run_ref=parts[2]))
                self._reply(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                self._serve("POST")

            def do_GET(self) -> None:  # noqa: N802
                self._serve("GET")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

        return Handler
