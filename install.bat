@echo off
REM Codeably — one-click setup for Windows.
cd /d "%~dp0"

echo === Codeably setup ===

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment .venv ...
  python -m venv .venv
)

echo Installing dependencies...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt -q

echo.
echo Setup complete. Starting Codeably...
echo.
call run.bat
