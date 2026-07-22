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

require_free_port() {
    local port="$1"
    local service="$2"
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "❌ $service port $port is already in use:"
        lsof -nP -iTCP:"$port" -sTCP:LISTEN
        echo "Set a different port with POLYBOB_API_PORT or POLYBOB_DASHBOARD_PORT."
        exit 1
    fi
}

# 设置信号处理
cleanup() {
    local exit_code=$?
    trap - EXIT INT
    echo ""
    echo "🛑 Stopping all services..."

    # 先发送 SIGTERM，让进程优雅退出
    [ -n "$API_PID" ] && kill -TERM "$API_PID" 2>/dev/null
    [ -n "$DASHBOARD_PID" ] && kill -TERM "$DASHBOARD_PID" 2>/dev/null

    # 等待进程退出
    [ -n "$API_PID" ] && wait "$API_PID" 2>/dev/null
    [ -n "$DASHBOARD_PID" ] && wait "$DASHBOARD_PID" 2>/dev/null

    echo "✅ All services stopped"
    exit $exit_code
}

trap cleanup EXIT
trap 'exit 130' INT

echo "╔═══════════════════════════════════════╗"
echo "║     POLYBOB COMPLETE STARTUP          ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 检查 conda
if ! command -v conda &> /dev/null; then
    echo "❌ Error: conda is not installed"
    exit 1
fi

CONDA_ENV_NAME="${CONDA_ENV_NAME:-polybob}"

# 激活 conda 环境
eval "$(conda shell.bash hook)"
echo "🔧 Activating conda environment: $CONDA_ENV_NAME"
conda activate "$CONDA_ENV_NAME"

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

# 只检查端口，不终止其他项目的进程
echo "🔎 Checking ports $API_PORT and $DASHBOARD_PORT..."
require_free_port "$API_PORT" "API"
require_free_port "$DASHBOARD_PORT" "Dashboard"

# 启动 API (禁用输出缓冲)
echo ""
echo "🚀 Starting API server..."
POLYBOB_API_PORT="$API_PORT" python -u -m apps.api.main &
API_PID=$!
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

# 等待用户中断
trap 'exit 130' INT
trap cleanup EXIT

# 保持脚本运行
wait
