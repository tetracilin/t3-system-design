"""Command line entry: ``python -m t3desk [--browser]`` and ``python -m t3desk bootstrap``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    from t3desk import bootstrap

    parser = argparse.ArgumentParser(prog="t3desk", description="T3 Desk")
    parser.add_argument("--browser", action="store_true", help="serve the UI to the default browser")
    sub = parser.add_subparsers(dest="command")
    boot = sub.add_parser("bootstrap", help="create tables and fields in a Teable base")
    bootstrap.add_arguments(boot)
    return parser


def run_app(browser: bool) -> int:
    """Start the local server, then show the UI in a native window or the default browser."""
    import logging
    import time

    import importlib

    from t3desk import platform

    try:
        # importlib honours a blocked/missing module even if the package attribute is cached
        server = importlib.import_module("t3desk.server")
    except ImportError as exc:
        print(f"The T3 Desk UI is not built yet ({exc}).", file=sys.stderr)
        return 2

    log = logging.getLogger("t3desk.main")
    home = platform.config_dir()
    server.setup_logging(home)
    app = server.App(home)
    running = server.make_server(app).start()
    log.info("serving %s", running.url)
    try:
        if not browser and platform.window_available():
            import webview

            try:
                webview.create_window("T3 Desk", running.url, width=1366, height=768, resizable=True, min_size=(960, 600))
                webview.start()
                return 0
            except Exception as exc:  # pywebview raises assorted errors when the OS web view is missing
                log.warning("native window failed (%s: %s); using the browser", type(exc).__name__, exc)
                print(f"Native window failed ({exc}); falling back to the browser.", file=sys.stderr)
        if not platform.open_in_browser(running.url):
            print(f"Open this address in a browser: {running.url}")
        print(f"T3 Desk is running at {running.url}  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    finally:
        running.stop()
        app.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        from t3desk import bootstrap

        return bootstrap.run_cli(args)
    return run_app(args.browser)


if __name__ == "__main__":
    raise SystemExit(main())
