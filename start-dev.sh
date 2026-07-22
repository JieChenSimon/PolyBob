#!/usr/bin/env bash
#
# start-dev.sh — 开发模式，带热加载 (hot reload)。
#
# 与 start-all.sh 的区别：
#   - API 用 uvicorn --reload：改动 apps/ services/ libs/ 下的 Python 后自动重启。
#   - Dashboard 用 `next dev` (Fast Refresh)：改动 .tsx/.css 后浏览器自动热更新，
#     无需手动重新 build。
#
# 用法：
#   ./start-dev.sh
#   POLYBOB_API_PORT=28000 POLYBOB_DASHBOARD_PORT=23001 ./start-dev.sh
#
# 生产模式（无热加载、dashboard 预构建）仍然用 ./start-all.sh。

set -euo pipefail
cd "$(dirname "$0")"

# 打开后端热加载（apps.api.main 里 uvicorn.run(..., reload=settings.api_reload)）
export API_RELOAD=true
# 让 dashboard 走 `npm run dev` 分支（start-all.sh 已支持 DASHBOARD_MODE=dev）
export DASHBOARD_MODE=dev

echo "🔥 开发模式：API 与 Dashboard 均已开启热加载。"
echo "   - 改 Python：uvicorn 自动重启"
echo "   - 改前端：浏览器自动热更新，无需重新 build"
echo ""

exec ./start-all.sh
