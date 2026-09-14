#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_PORT="${PORT:-8877}"
PROJECT_PY="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$PROJECT_PY" ]]; then
  echo "ASR virtual environment was not found. Create .venv and install backend/requirements.txt first."
  exit 1
fi

cd "$SCRIPT_DIR"
echo "VD10 ASR demo: http://127.0.0.1:${DEMO_PORT}"
exec "$PROJECT_PY" -m uvicorn backend.server:app --host 127.0.0.1 --port "$DEMO_PORT"
