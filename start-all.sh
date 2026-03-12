#!/bin/bash

# PolyBob 完整启动脚本 - 启动所有服务

set -e

echo "╔═══════════════════════════════════════╗"
echo "║     POLYBOB COMPLETE STARTUP          ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 检查 conda
if ! command -v conda &> /dev/null; then
    echo "❌ Error: conda is not installed"
    exit 1
fi

# 激活 conda 环境
echo "🔧 Activating conda environment..."
eval "$(conda shell.bash hook)"
conda activate polybob

# 检查 .env
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
fi

# 启动 API
echo ""
echo "🚀 Starting API server..."
python -m apps.api.main &
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
    npm run dev &
else
    echo "🏗️  Building dashboard for production mode..."
    npm run build
    echo "✨ Running dashboard in production mode..."
    npm run start &
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
trap "echo ''; echo '🛑 Stopping all services...'; kill $API_PID $DASHBOARD_PID 2>/dev/null; exit 0" INT

# 保持脚本运行
wait
