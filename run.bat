@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else (
  set PY=python
)

start "" %PY% api\main.py
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8765/ui
echo Codeably is running. Close this window to keep it running in the background,
echo or press Ctrl+C in the server window to stop it.
