#!/usr/bin/env bash
# Serve the app locally, then open http://localhost:8000/web/
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8000}"
echo "Serving on http://localhost:${PORT}/web/  (Ctrl-C to stop)"
python3 -m http.server "$PORT"
