#!/usr/bin/env bash
# Starts the API and the frontend dev server, and stops both on Ctrl-C.
#   bash scripts/run_dev.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=".venv/Scripts/python.exe"
if [ ! -x "$PYTHON" ]; then
  echo "No virtualenv found. Create one first:"
  echo "  python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Starting API on http://localhost:8000 ..."
PYTHONPATH=backend "$PYTHON" -m uvicorn app.main:app --reload --port 8000 &
pids+=($!)

if [ -d frontend/node_modules ]; then
  echo "Starting frontend on http://localhost:5173 ..."
  (cd frontend && npm run dev) &
  pids+=($!)
else
  echo "frontend/node_modules is missing - run 'npm install' in frontend/ first."
fi

cat <<'EOF'

API docs : http://localhost:8000/docs
Health   : http://localhost:8000/meta/health
App      : http://localhost:5173

No data on the map or dashboard? Run:
  python scripts/seed_demo_data.py --cases 120

EOF

wait
