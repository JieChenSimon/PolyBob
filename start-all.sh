#!/bin/bash

# PolyBob 完整启动脚本 - 启动所有服务

set -e

API_PID=""
DASHBOARD_PID=""
API_PORT="${POLYBOB_API_PORT:-}"
DASHBOARD_PORT="${POLYBOB_DASHBOARD_PORT:-}"

read_env_value() {
    local key="$1"
    sed -n "s/^${key}=//p" .env 2>/dev/null | tail -n 1
}

# 进程生命周期保障(信号 / 进程组 / 看门狗)由 scripts/run-guard.sh 统一提供,
# start.sh 和 start-dashboard.sh 用的是同一份。
# shellcheck source=scripts/run-guard.sh
. "$(dirname "$0")/scripts/run-guard.sh"

echo "╔═══════════════════════════════════════╗"
echo "║     POLYBOB COMPLETE STARTUP          ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 检查 uv
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed"
    echo "   https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# 精确同步项目自己的 .venv；不依赖全局 Python 环境。
echo "🔧 Syncing locked Python environment"
UV_SYNC_ARGS=(--locked --quiet)
if [ -n "${POLYBOB_UV_EXTRA:-}" ]; then
    UV_SYNC_ARGS+=(--extra "$POLYBOB_UV_EXTRA")
fi
uv sync "${UV_SYNC_ARGS[@]}"
export POLYBOB_AKSHARE_PYTHON="${POLYBOB_AKSHARE_PYTHON:-$PWD/.venv/bin/python}"

# 检查 .env
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
fi

# Export root configuration so both FastAPI and the Next.js server can read it.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

API_PORT="${API_PORT:-$(read_env_value POLYBOB_API_PORT)}"
DASHBOARD_PORT="${DASHBOARD_PORT:-$(read_env_value POLYBOB_DASHBOARD_PORT)}"
API_PORT="${API_PORT:-18000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-13001}"

# 启动是幂等的:上次运行的残留先停掉,所以连跑两次得到一个实例而不是端口冲突。
run_guard_init
run_guard_own_ports "$API_PORT" "$DASHBOARD_PORT"
run_guard_arm

# 检查端口。属于 PolyBob 自己的旧实例会被回收;别的项目的进程不会被碰。
echo "🔎 Checking ports $API_PORT and $DASHBOARD_PORT..."
run_guard_require_free_port "$API_PORT" "API"
run_guard_require_free_port "$DASHBOARD_PORT" "Dashboard"

# 启动 API (禁用输出缓冲)
echo ""
echo "🚀 Starting API server..."
POLYBOB_API_PORT="$API_PORT" uv run --locked --no-sync python -u -m apps.api.main &
API_PID=$!
run_guard_write_pid api "$API_PID"
echo "   API PID: $API_PID"

# 等待 API 启动
echo "⏳ Waiting for API to start..."
API_READY=false
for _ in {1..30}; do
    if curl -fsS "http://127.0.0.1:$API_PORT" >/dev/null 2>&1; then
        API_READY=true
        break
    fi
    if ! kill -0 "$API_PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

if [ "$API_READY" = true ]; then
    echo "✅ API is running at http://localhost:$API_PORT"
else
    echo "❌ API failed to start"
    kill $API_PID 2>/dev/null || true
    exit 1
fi

# 启动 Web Dashboard
echo ""
echo "🎨 Starting Web Dashboard..."
cd apps/dashboard

DASHBOARD_MODE="${DASHBOARD_MODE:-prod}"

if [ ! -d "node_modules" ]; then
    echo "📦 Installing dashboard dependencies..."
    npm install
fi

if [ "$DASHBOARD_MODE" = "dev" ]; then
    echo "🧪 Running dashboard in development mode..."
    POLYBOB_DASHBOARD_PORT="$DASHBOARD_PORT" \
    NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:$API_PORT" \
    npm run dev &
else
    echo "🏗️  Building dashboard for production mode..."
    NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:$API_PORT" npm run build
    echo "✨ Running dashboard in production mode..."
    POLYBOB_DASHBOARD_PORT="$DASHBOARD_PORT" \
    NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:$API_PORT" \
    npm run start &
fi

DASHBOARD_PID=$!
cd ../..
run_guard_write_pid dashboard "$DASHBOARD_PID"
echo "   Dashboard PID: $DASHBOARD_PID"

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║         ALL SERVICES STARTED          ║"
echo "╠═══════════════════════════════════════╣"
printf "║ API:       http://localhost:%-9s ║\n" "$API_PORT"
printf "║ Dashboard: http://localhost:%-9s ║\n" "$DASHBOARD_PORT"
printf "║ API Docs:  http://localhost:%-4s/docs ║\n" "$API_PORT"
printf "║ Mode:      %-27s ║\n" "$DASHBOARD_MODE"
echo "╠═══════════════════════════════════════╣"
echo "║ Press Ctrl+C to stop all services     ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 信号处理由 run_guard_arm 一次装好,这里不再重复注册
# (以前在这里只重装 INT/EXIT,把前面装好的 HUP 处理覆盖掉了)。

# 保持脚本运行
wait
