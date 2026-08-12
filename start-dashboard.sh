#!/bin/bash

# Start the PolyBob dashboard from the repository root.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 同一份进程生命周期保障。dashboard 尤其需要:``next dev`` 会派生 next-server,
# 真正占着端口的是那个孙进程,它不是本脚本的 job。
# shellcheck source=scripts/run-guard.sh
. "$ROOT_DIR/scripts/run-guard.sh"
DASHBOARD_DIR="$ROOT_DIR/apps/dashboard"
DASHBOARD_PORT="${POLYBOB_DASHBOARD_PORT:-}"

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed"
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

uv sync --locked --quiet
export POLYBOB_AKSHARE_PYTHON="${POLYBOB_AKSHARE_PYTHON:-$ROOT_DIR/.venv/bin/python}"

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

run_guard_init
run_guard_own_ports "$DASHBOARD_PORT"
run_guard_arm
run_guard_require_free_port "$DASHBOARD_PORT" "Dashboard"

echo "Starting PolyBob dashboard at http://localhost:$DASHBOARD_PORT"
POLYBOB_DASHBOARD_PORT="$DASHBOARD_PORT" npm run dev &
run_guard_write_pid dashboard "$!"
wait
