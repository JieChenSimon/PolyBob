#!/bin/bash
#
# stop-all.sh — 停掉所有 PolyBob 进程，不管它们是怎么被启动的。
#
# start-all.sh 正常退出时会自己清理；这个脚本是给不正常的情况用的：
# 终端被强制关掉、脚本被 kill -9、或者你就是想确认现在一个都没剩。
#
#   ./stop-all.sh          # 停掉默认端口上的服务
#   ./stop-all.sh --all    # 连非默认端口上的 PolyBob 进程一起扫

set -uo pipefail
cd "$(dirname "$0")"

RUN_DIR=".polybob/run"
OURS="apps\.api\.main|uvicorn apps\.api|next dev|next-server|start-all\.sh"

read_env_value() { sed -n "s/^${1}=//p" .env 2>/dev/null | tail -n 1; }
API_PORT="${POLYBOB_API_PORT:-$(read_env_value POLYBOB_API_PORT)}"
DASHBOARD_PORT="${POLYBOB_DASHBOARD_PORT:-$(read_env_value POLYBOB_DASHBOARD_PORT)}"
API_PORT="${API_PORT:-18000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-13001}"

stopped=0

kill_pid() {
    local pid="$1" why="$2"
    kill -0 "$pid" 2>/dev/null || return 0
    ps -o command= -p "$pid" 2>/dev/null | grep -qE "$OURS" || return 0
    echo "  🛑 $why: pid $pid — $(ps -o command= -p "$pid" 2>/dev/null | cut -c1-60)"
    kill -TERM "$pid" 2>/dev/null
    stopped=1
}

echo "🔎 Looking for PolyBob processes…"

# 1) The pid files written by the last run.
for name in session api dashboard; do
    [ -f "$RUN_DIR/$name.pid" ] || continue
    kill_pid "$(cat "$RUN_DIR/$name.pid" 2>/dev/null)" "from $name.pid"
done

# 2) Whatever is holding our ports — catches the next-server grandchild, which
#    is not any script's direct job.
for port in "$API_PORT" "$DASHBOARD_PORT"; do
    for pid in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
        kill_pid "$pid" "on port $port"
    done
done

# 3) --all: anything of ours anywhere, including non-default ports.
if [ "${1:-}" = "--all" ]; then
    for pid in $(pgrep -f "apps\.api\.main|uvicorn apps\.api|next dev|next-server" 2>/dev/null); do
        kill_pid "$pid" "repo-wide sweep"
    done
fi

if [ "$stopped" = 0 ]; then
    echo "✅ Nothing running."
    rm -f "$RUN_DIR"/*.pid 2>/dev/null
    exit 0
fi

sleep 3

# Anything that ignored SIGTERM gets SIGKILL — the point of this script is that
# afterwards there is definitely nothing left.
for port in "$API_PORT" "$DASHBOARD_PORT"; do
    for pid in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
        ps -o command= -p "$pid" 2>/dev/null | grep -qE "$OURS" || continue
        echo "  ⚠️  pid $pid ignored SIGTERM — sending SIGKILL"
        kill -KILL "$pid" 2>/dev/null
    done
done

rm -f "$RUN_DIR"/*.pid 2>/dev/null

echo ""
for port in "$API_PORT" "$DASHBOARD_PORT"; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "❌ Port $port is still in use:"
        lsof -nP -iTCP:"$port" -sTCP:LISTEN
        exit 1
    fi
done
echo "✅ All PolyBob services stopped; ports $API_PORT and $DASHBOARD_PORT are free."
