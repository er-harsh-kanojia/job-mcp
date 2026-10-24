#!/usr/bin/env bash
# ==============================================================================
# Job MCP - Full Automated Setup Script (Bash / Linux / macOS / Git Bash)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "               Job MCP Automated Setup                      "
echo "============================================================"

# 1. Python check
PYTHON=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
fi

if [[ -z "$PYTHON" ]]; then
    echo "Python 3 nahi mila. Please install Python 3.10+ and re-run." >&2
    exit 1
fi
echo "[OK] Found Python: $($PYTHON --version)"

# 2. Node & npm check
if command -v npm >/dev/null 2>&1; then
    echo "[OK] Found Node: $(node -v), npm: $(npm -v)"
    HAS_NPM=true
else
    echo "[!] Node / npm not found. Frontend will require pre-built web/dist."
    HAS_NPM=false
fi

# 3. Create .venv
if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment in .venv..."
    "$PYTHON" -m venv .venv
fi

VENV_PY=".venv/bin/python"
if [[ -f ".venv/Scripts/python.exe" ]]; then
    VENV_PY=".venv/Scripts/python.exe"
fi

# 4. Install requirements
echo "Installing Python requirements..."
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r requirements.txt --quiet
echo "[OK] Python dependencies installed."

# 5. Install Playwright Chromium
echo "Installing Playwright Chromium..."
"$VENV_PY" -m playwright install chromium
echo "[OK] Chromium browser installed."

# 6. Build web if npm available
if [[ "$HAS_NPM" = true ]]; then
    echo "Building frontend bundle..."
    (cd web && npm install --quiet && npm run build)
    echo "[OK] Frontend built."
fi

# 7. Environment configuration
if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        echo "[OK] Created .env from .env.example"
    else
        touch .env
    fi
    echo "--> IMPORTANT: Open .env and add your ANTHROPIC_API_KEY or OPENAI_API_KEY"
    echo "    for AI Resume Review, ATS Scorer, and Mock Interviews."
fi

if [[ ! -f "config.json" ]] && [[ -f "config.example.json" ]]; then
    cp config.example.json config.json
    echo "[OK] Created config.json from config.example.json"
fi

echo "============================================================"
echo "Job MCP Setup Complete! Run './start.sh' to start."
echo "============================================================"
