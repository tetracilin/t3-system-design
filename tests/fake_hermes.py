"""In-process fake Hermes API server for the hermes_skill plugin tests.

Mimics the shapes in docs/reference/hermes-api-server.md: Bearer auth, ``POST /v1/runs`` with
``{"input", "instructions", "session_id"}`` and an ``Idempotency-Key`` header returning
``{"run_id", "status": "started"}``, ``GET /v1/runs/{run_id}`` returning ``status`` and ``output``,
and HTTP 429 ``Too many concurrent runs (max N)``.

UNVERIFIED: the documentation does not give the status strings of ``GET /v1/runs/{id}`` (this fake
uses running / completed / failed) or what ``output`` looks like (this fake returns the JSON
``{"link": ...}`` the plugin asks for).
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "hermes-test-token"


class FakeHermes:
    def __init__(self, *, polls_until_done: int = 2, link: str = "http://nas.invalid/docs/RFQ.docx",
                 fail: bool = False, token: str = TOKEN, busy_starts: int = 0):
        self.polls_until_done = polls_until_done
        self.link = link
        self.fail = fail
        self.token = token
        self.busy_starts = busy_starts  # the next N starts get HTTP 429
        # what arrived: method, path, body, idempotency_key (the Authorization header is never kept)
        self.requests: list[dict[str, Any]] = []
        self.runs: dict[str, dict[str, Any]] = {}  # run_id -> skill, payload, body, polls
        self._by_key: dict[str, str] = {}
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

    def _create_run(self, body: dict[str, Any], key: str | None) -> tuple[int, dict[str, Any]]:
        with self._lock:
            if key and key in self._by_key:  # idempotent replay: same run, no new one
                return 200, {"run_id": self._by_key[key], "status": "started"}
            if self.busy_starts > 0:
                self.busy_starts -= 1
                return 429, {"error": "Too many concurrent runs (max 10)"}
            text = str(body.get("input", ""))
            skill = re.search(r'skill "([^"]+)"', text)
            marker = "Payload JSON:\n"
            payload = json.loads(text.split(marker, 1)[1]) if marker in text else None
            ref = f"run-{len(self.runs) + 1:04d}"
            self.runs[ref] = {"skill": skill.group(1) if skill else "", "payload": payload, "body": body, "polls": 0}
            if key:
                self._by_key[key] = ref
            return 200, {"run_id": ref, "status": "started"}

    def _get_run(self, ref: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            run = self.runs.get(ref)
            if run is None:
                return 404, {"error": "unknown run"}
            run["polls"] += 1
            if run["polls"] < self.polls_until_done:
                return 200, {"run_id": ref, "status": "running", "output": None}
            if self.fail:
                return 200, {"run_id": ref, "status": "failed", "output": None, "error": "skill crashed"}
            return 200, {"run_id": ref, "status": "completed", "output": json.dumps({"link": self.link}),
                         "usage": {}, "runtime": {}}

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
                key = self.headers.get("Idempotency-Key")
                fake.requests.append({"method": method, "path": self.path, "body": body, "idempotency_key": key})
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    return self._reply(401, {"error": "bad token"})
                parts = self.path.strip("/").split("/")
                if method == "POST" and parts == ["v1", "runs"]:
                    if not isinstance(body, dict) or "input" not in body:
                        return self._reply(400, {"error": "input is required"})
                    if key is not None and not 1 <= len(key) <= 255:
                        return self._reply(400, {"error": "bad Idempotency-Key"})
                    return self._reply(*fake._create_run(body, key))
                if method == "GET" and len(parts) == 3 and parts[:2] == ["v1", "runs"]:
                    return self._reply(*fake._get_run(parts[2]))
                self._reply(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                self._serve("POST")

            def do_GET(self) -> None:  # noqa: N802
                self._serve("GET")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

        return Handler
