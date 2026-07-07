#!/usr/bin/env bash
# Starts the Codeably API server and opens the UI in your browser.
set -e
cd "$(dirname "$0")"

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

"$PY" api/main.py &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null" EXIT

# Wait for the server to come up, then open the UI.
for i in $(seq 1 40); do
  if curl -s http://127.0.0.1:8765/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

URL="http://127.0.0.1:8765/ui"
if command -v open >/dev/null 2>&1; then
  open "$URL"          # macOS
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"       # Linux
else
  echo "Open $URL in your browser."
fi

wait $SERVER_PID
