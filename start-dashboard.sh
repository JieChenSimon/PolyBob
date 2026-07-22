#!/bin/bash

# Start the PolyBob dashboard from the repository root.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$ROOT_DIR/apps/dashboard"
DASHBOARD_PORT="${POLYBOB_DASHBOARD_PORT:-}"

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT_DIR/.env"
    set +a
fi

if [ -z "$DASHBOARD_PORT" ] && [ -f "$ROOT_DIR/.env" ]; then
    DASHBOARD_PORT="$(sed -n 's/^POLYBOB_DASHBOARD_PORT=//p' "$ROOT_DIR/.env" | tail -n 1)"
fi
DASHBOARD_PORT="${DASHBOARD_PORT:-13001}"

if [ ! -d "$DASHBOARD_DIR" ]; then
    echo "Error: dashboard directory not found: $DASHBOARD_DIR"
    exit 1
fi

cd "$DASHBOARD_DIR"

if [ ! -d "node_modules" ]; then
    echo "Installing dashboard dependencies..."
    npm install
fi

if lsof -nP -iTCP:"$DASHBOARD_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Error: dashboard port $DASHBOARD_PORT is already in use:"
    lsof -nP -iTCP:"$DASHBOARD_PORT" -sTCP:LISTEN
    echo "Set POLYBOB_DASHBOARD_PORT to a free port."
    exit 1
fi

echo "Starting PolyBob dashboard at http://localhost:$DASHBOARD_PORT"
POLYBOB_DASHBOARD_PORT="$DASHBOARD_PORT" npm run dev
