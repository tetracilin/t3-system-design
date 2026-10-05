"""The only module with OS-specific code: config folder, default browser, window backend."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

APP_DIR_NAME = "T3Desk"
HOME_ENV = "T3DESK_HOME"


def config_dir() -> Path:
    """Per-user folder for the SQLite file, the log and the restricted token file.

    ``T3DESK_HOME`` overrides it (tests, smoke script, portable installs)."""
    override = os.environ.get(HOME_ENV)
    if override:
        path = Path(override)
    elif sys.platform.startswith("win"):
        path = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_DIR_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "t3desk"
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_in_browser(url: str) -> bool:
    """Open ``url`` in the default browser. Returns False when no browser could be started."""
    try:
        return bool(webbrowser.open(url))
    except webbrowser.Error:
        return False


def shortcut_modifier() -> str:
    """Name of the primary shortcut key shown in hints: Cmd on macOS, Ctrl elsewhere."""
    return "Cmd" if sys.platform == "darwin" else "Ctrl"


def window_available() -> bool:
    """True when pywebview can be imported (a native window is possible)."""
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True
