#!/bin/bash

# PolyBob 完整启动脚本 - 启动所有服务

set -e

API_PID=""
DASHBOARD_PID=""

# 设置信号处理
cleanup() {
    local exit_code=$?
    echo ""
    echo "🛑 Stopping all services..."

    # 先发送 SIGTERM，让进程优雅退出
    [ -n "$API_PID" ] && kill -TERM "$API_PID" 2>/dev/null
    [ -n "$DASHBOARD_PID" ] && kill -TERM "$DASHBOARD_PID" 2>/dev/null

    # 等待进程退出
    [ -n "$API_PID" ] && wait "$API_PID" 2>/dev/null
    [ -n "$DASHBOARD_PID" ] && wait "$DASHBOARD_PID" 2>/dev/null

    # 强制清理残留
    lsof -ti:8000 | xargs -r kill -9 2>/dev/null
    lsof -ti:3001 | xargs -r kill -9 2>/dev/null

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

CONDA_ENV_NAME="${CONDA_ENV_NAME:-${CONDA_DEFAULT_ENV:-}}"

# 激活 conda 环境
eval "$(conda shell.bash hook)"
if [ -n "$CONDA_ENV_NAME" ]; then
    echo "🔧 Activating conda environment: $CONDA_ENV_NAME"
    conda activate "$CONDA_ENV_NAME"
else
    echo "🔧 Using current shell environment"
fi

# 检查 .env
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
fi

# 清理可能占用的端口
echo "🧹 Cleaning up ports 8000 and 3001..."
lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
lsof -ti:3001 | xargs -r kill -9 2>/dev/null || true
sleep 1

# 启动 API (禁用输出缓冲)
echo ""
echo "🚀 Starting API server..."
stdbuf -oL -eL python -m apps.api.main &
API_PID=$!
echo "   API PID: $API_PID"

# 等待 API 启动
echo "⏳ Waiting for API to start..."
sleep 3

# 检查 API 是否运行
if curl -s http://localhost:8000 > /dev/null; then
    echo "✅ API is running at http://localhost:8000"
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
    PORT=3001 npm run dev &
else
    echo "🏗️  Building dashboard for production mode..."
    npm run build
    echo "✨ Running dashboard in production mode..."
    PORT=3001 npm run start &
fi

DASHBOARD_PID=$!
cd ../..
echo "   Dashboard PID: $DASHBOARD_PID"

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║         ALL SERVICES STARTED          ║"
echo "╠═══════════════════════════════════════╣"
echo "║ API:       http://localhost:8000      ║"
echo "║ Dashboard: http://localhost:3001      ║"
echo "║ API Docs:  http://localhost:8000/docs ║"
echo "║ Mode:      ${DASHBOARD_MODE}                   ║"
echo "╠═══════════════════════════════════════╣"
echo "║ Press Ctrl+C to stop all services     ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 等待用户中断
trap 'exit 130' INT
trap cleanup EXIT

# 保持脚本运行
wait
