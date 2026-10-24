#!/usr/bin/env bash
# Start the Job MCP web UI and API from the project directory.

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ -x "$PROJECT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
elif [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "Python nahi mila. Python 3 install karo ya project mein .venv banao." >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/web/dist/index.html" ]]; then
  echo "Frontend build nahi mila: web/dist/index.html" >&2
  echo "Build karne ke liye: cd web && npm install && npm run build" >&2
  exit 1
fi

echo "Job MCP start ho raha hai: http://127.0.0.1:8765"
echo "Band karne ke liye is terminal mein Ctrl+C dabao."
exec "$PYTHON" "$PROJECT_DIR/app.py" "$@"
