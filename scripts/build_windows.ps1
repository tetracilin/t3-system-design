# Build T3 Desk on Windows as a PyInstaller one-folder app.
# Run from the repository root inside the project venv. PyInstaller must already be installed
# (this script does not install anything):  pip install pyinstaller
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "pyinstaller not found. Install it in the venv first (pip install pyinstaller)."
}

pyinstaller --noconfirm --clean --onedir --windowed `
    --name T3Desk `
    --paths $Root `
    --add-data "t3desk/data;t3desk/data" `
    --add-data "t3desk/ui;t3desk/ui" `
    --add-data "plugins;plugins" `
    --collect-submodules t3desk `
    t3desk/__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Built: $Root\dist\T3Desk\T3Desk.exe"
Write-Host "Packaging is UNVERIFIED on a clean machine: run the exe and check one screen loads."
