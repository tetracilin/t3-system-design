#!/usr/bin/env bash
# Build T3 Desk on Linux as a PyInstaller one-folder app.
# Run inside the project venv. PyInstaller must already be installed (this script does not install it).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v pyinstaller >/dev/null 2>&1 || { echo "pyinstaller not found; install it in the venv first" >&2; exit 1; }

pyinstaller --noconfirm --clean --onedir \
    --name T3Desk \
    --paths . \
    --add-data "t3desk/data:t3desk/data" \
    --add-data "t3desk/ui:t3desk/ui" \
    --add-data "plugins:plugins" \
    --collect-submodules t3desk \
    t3desk/__main__.py

echo "Built: dist/T3Desk/T3Desk"
echo "Packaging on Linux is UNVERIFIED until run on a clean machine."
