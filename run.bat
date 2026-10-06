@echo off
rem Starts T3 Desk with the project's own virtual environment. Extra arguments are passed through, e.g. run.bat --browser
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run: python -m venv .venv ^&^& .venv\Scripts\python -m pip install -e ".[dev]"
  exit /b 1
)
".venv\Scripts\python.exe" -m t3desk %*
