#!/usr/bin/env bash
# Codeably — one-click setup for macOS / Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/install.sh | bash
#
# or, after cloning:
#   ./install.sh
#
# This creates a local virtualenv, installs dependencies, and starts the
# API server + opens the UI in your browser. Re-run `./run.sh` afterwards
# to start it again without reinstalling anything.

set -e
cd "$(dirname "$0")"

echo "── Codeably setup ─────────────────────────────────────────"

PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first: https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv) ..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Installing dependencies ..."
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q

echo ""
echo "Setup complete. Starting Codeably ..."
echo ""
./run.sh
