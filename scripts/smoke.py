"""Smoke test: start the server on a free port, load one screen and its data, then exit.

    python scripts/smoke.py

Uses a throw-away config folder, so it never touches the real user's drafts or settings.
It talks only to 127.0.0.1 and does not need Teable. Exit code 0 means the app started.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from t3desk import platform, server  # noqa: E402


def get(url: str, session: str | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={server.SESSION_HEADER: session} if session else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="t3desk-smoke-") as home:
        os.environ[platform.HOME_ENV] = home
        app = server.App(platform.config_dir(), keyring_module=None)
        running = server.make_server(app).start()
        try:
            status, page = get(running.url)
            assert status == 200 and b"T3 Desk" in page, "index.html did not load"
            for name in ("app.js", "tree.js", "style.css"):
                assert get(running.url + name)[0] == 200, f"{name} did not load"
            meta = json.loads(get(running.url + "api/meta", app.session)[1])
            state = json.loads(get(running.url + "api/state", app.session)[1])
            trees = json.loads(get(running.url + "api/trees", app.session)[1])
            assert len(meta["screens"]) == 11, "expected 11 screens"
            assert state["connection"]["state"] == "unconfigured"
            assert set(trees["trees"]) == {"system_design", "designer", "engineer"}
            print(f"smoke ok: {running.url} screens={len(meta['screens'])} trees={len(trees['trees'])}")
            return 0
        except (AssertionError, OSError, KeyError, ValueError) as exc:
            print(f"smoke FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            running.stop()
            app.close()


if __name__ == "__main__":
    raise SystemExit(main())
