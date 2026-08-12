#!/bin/bash

# PolyBob 启动脚本

set -e
cd "$(dirname "$0")"

# 同一份进程生命周期保障:关终端 / Ctrl+C / kill -9 之后不留孤儿。
# shellcheck source=scripts/run-guard.sh
. "$(dirname "$0")/scripts/run-guard.sh"

echo "Starting PolyBob..."

# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed"
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

API_PORT="${POLYBOB_API_PORT:-}"

# 精确同步锁文件；不依赖调用者碰巧激活的 Python 环境。
echo "Syncing locked Python environment..."
UV_SYNC_ARGS=(--locked --quiet)
if [ -n "${POLYBOB_UV_EXTRA:-}" ]; then
    UV_SYNC_ARGS+=(--extra "$POLYBOB_UV_EXTRA")
fi
uv sync "${UV_SYNC_ARGS[@]}"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please edit .env file with your configuration"
    exit 1
fi

if [ -z "$API_PORT" ]; then
    API_PORT="$(sed -n 's/^POLYBOB_API_PORT=//p' .env | tail -n 1)"
fi
API_PORT="${API_PORT:-18000}"

# 启动服务
run_guard_init
run_guard_own_ports "$API_PORT"
run_guard_arm
run_guard_require_free_port "$API_PORT" "API"

echo "Starting API server at http://localhost:$API_PORT..."
POLYBOB_API_PORT="$API_PORT" uv run --locked --no-sync python -m apps.api.main &
run_guard_write_pid api "$!"
wait
