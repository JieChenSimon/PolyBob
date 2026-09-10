#!/bin/bash
#
# run-guard.sh — 所有启动脚本共用的进程生命周期保障。
#
# 要保证的一件事：**你关掉终端或停止运行之后，PolyBob 一个进程都不该活着。**
#
# 之前不是这样。一个 start-all.sh 会话活了四天多：终端早就关了，但脚本只 trap 了
# EXIT 和 INT——没有 HUP，而关终端发的正是 HUP。它一直占着 18000/13001，跑的还是四天前
# 的代码，直到下次启动失败才被发现。
#
# 三层保障，因为单独任何一层都有漏洞：
#
#   1. **信号**：EXIT / INT / TERM / HUP 全都收尾。HUP 是之前漏掉的那个。
#   2. **进程组**：清理时 kill 整个进程组，不只是两个直接子进程。``npm run dev``
#      会派生 ``next-server``,真正占着 dashboard 端口的是那个孙进程,它不是任何
#      脚本的 job,wait 不到。
#   3. **看门狗**：一个脱离作业控制的轮询进程。脚本被 ``kill -9`` 时 trap 根本没机会
#      运行——而那正是产生孤儿的时刻。看门狗发现父进程没了就替它收尾。
#
# 用法（在启动脚本里）：
#
#     source "$(dirname "$0")/scripts/run-guard.sh"
#     run_guard_init                       # 建 run 目录、登记本次会话
#     run_guard_own_ports 18000 13001      # 声明本次会话拥有哪些端口
#     run_guard_require_free_port 18000 API
#     run_guard_arm                        # 装信号处理 + 看门狗
#     run_guard_write_pid api "$PID"       # 记录子进程(可选)

# 只认这个仓库自己的入口，绝不误伤别的项目的 python/node。
RUN_GUARD_PATTERN='apps\.api\.main|uvicorn apps\.api|next dev|next-server|start-all\.sh'
# 绝对路径:start-dashboard.sh 会先 cd 进 apps/dashboard,相对路径会把 run 目录
# 建到错误的地方,于是各脚本互相看不见对方的 pid 文件。
RUN_GUARD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_GUARD_DIR="$RUN_GUARD_ROOT/.polybob/run"
RUN_GUARD_PORTS=""
RUN_GUARD_ARMED=""

run_guard_init() {
    mkdir -p "$RUN_GUARD_DIR"
    run_guard_prune_stale
    run_guard_stop_previous
    run_guard_write_pid session "$$"
}

# 清掉早已死去的会话留下的清单文件,否则会一直堆积。文件名就是会话 pid,进程不在了
# 就没人会再读它。
run_guard_prune_stale() {
    local file base
    for file in "$RUN_GUARD_DIR"/*.children "$RUN_GUARD_DIR"/*.done; do
        [ -f "$file" ] || continue
        base=$(basename "$file")
        base="${base%%.*}"
        kill -0 "$base" 2>/dev/null || rm -f "$file" 2>/dev/null
    done
    return 0
}

run_guard_write_pid() {
    echo "$2" > "$RUN_GUARD_DIR/$1.pid" 2>/dev/null || true
    # 同时记进本会话私有的清单。看门狗只认这份清单 + 真正的孤儿,绝不按端口乱杀,
    # 否则会误伤把我们回收掉的那个新会话。
    echo "$2" >> "$RUN_GUARD_DIR/$$.children" 2>/dev/null || true
}

run_guard_own_ports() {
    RUN_GUARD_PORTS="$*"
}

# 这个 pid 还活着,而且看起来确实是我们的?(pid 会被系统回收复用,所以要比对命令行)
run_guard_is_ours() {
    local pid="$1"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    ps -o command= -p "$pid" 2>/dev/null | grep -qE "$RUN_GUARD_PATTERN"
}

run_guard_port_pids() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null
}

# 上一次运行留下的东西,先停掉。启动因此是幂等的:连跑两次得到一个实例,而不是端口冲突。
run_guard_stop_previous() {
    local stopped=0 pid
    for name in api dashboard session; do
        local file="$RUN_GUARD_DIR/$name.pid"
        [ -f "$file" ] || continue
        pid=$(cat "$file" 2>/dev/null || true)
        rm -f "$file"
        run_guard_is_ours "$pid" || continue
        echo "♻️  停掉上次运行残留的 $name (pid $pid)"
        kill -TERM "$pid" 2>/dev/null || true
        stopped=1
    done
    [ "$stopped" = 1 ] && sleep 2
    return 0
}

run_guard_reclaim_port() {
    local port="$1" pid parent
    for pid in $(run_guard_port_pids "$port"); do
        # 连它的 start-all.sh 管家一起停,否则管家的 trap 会和我们抢,或者干脆活得比
        # 它照看的子进程还久。
        parent=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        if [ -n "$parent" ] && ps -o command= -p "$parent" 2>/dev/null | grep -q "start-all.sh"; then
            kill -TERM "$parent" 2>/dev/null || true
        fi
        kill -TERM "$pid" 2>/dev/null || true
    done
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        run_guard_port_pids "$port" >/dev/null 2>&1 || return 0
        [ -z "$(run_guard_port_pids "$port")" ] && return 0
        sleep 0.5
    done
    [ -z "$(run_guard_port_pids "$port")" ]
}

# 回收自己的旧实例是**默认行为**,不是开关。上一次运行跑的是它启动那一刻的代码,留着它
# 从来不是你想要的;而每次都让你手工排查,正是四天的陈旧 API 没被发现的原因。
# 确实想同时跑两个实例就设 POLYBOB_NO_RECLAIM=true。
run_guard_require_free_port() {
    local port="$1" service="$2" pid
    [ -n "$(run_guard_port_pids "$port")" ] || return 0

    for pid in $(run_guard_port_pids "$port"); do
        if ! run_guard_is_ours "$pid"; then
            echo "❌ $service 端口 $port 被非 PolyBob 的进程占用:"
            lsof -nP -iTCP:"$port" -sTCP:LISTEN
            echo "   用 POLYBOB_API_PORT / POLYBOB_DASHBOARD_PORT 换一个端口。"
            exit 1
        fi
    done

    if [ "${POLYBOB_NO_RECLAIM:-}" = "true" ]; then
        echo "❌ $service 端口 $port 被旧的 PolyBob 实例占用,而 POLYBOB_NO_RECLAIM=true,不动它:"
        lsof -nP -iTCP:"$port" -sTCP:LISTEN
        exit 1
    fi

    echo "♻️  $service 端口 $port 被旧的 PolyBob 实例占用 — 先停掉它。"
    if run_guard_reclaim_port "$port"; then
        echo "   ✅ 端口 $port 已回收。"
        return 0
    fi
    echo "❌ 无法释放端口 $port,请手动处理:"
    echo "   kill $(run_guard_port_pids "$port" | tr '\n' ' ')"
    exit 1
}

# 端口监听不等于服务可用：Next 的 next-server 可能已经 bind 端口，却卡在首轮
# 编译或请求处理里。启动入口必须等到一个真实 HTTP 响应后才能向操作者报告成功。
# 失败时交给现有 EXIT trap 回收整组子进程，不能遗留“端口在、页面死”的孤儿。
run_guard_wait_http() {
    local url="$1" service="$2" pid="$3" attempts="${4:-30}" attempt
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            echo "   ✅ $service 已就绪: $url"
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "   ❌ $service 进程在就绪前退出。"
            return 1
        fi
        sleep 1
    done
    echo "   ❌ $service 在 ${attempts}s 内没有返回 HTTP 响应。"
    return 1
}

# 扫掉本次会话端口上还活着的自己人。端口是抓住 next-server 孙进程最可靠的把手。
run_guard_sweep_ports() {
    local signal="${1:--TERM}" port pid
    for port in $RUN_GUARD_PORTS; do
        [ -n "$port" ] || continue
        for pid in $(run_guard_port_pids "$port"); do
            run_guard_is_ours "$pid" || continue
            kill "$signal" "$pid" 2>/dev/null || true
        done
    done
}

run_guard_cleanup() {
    local exit_code=$?
    [ -n "$RUN_GUARD_ARMED" ] || exit $exit_code
    trap - EXIT INT HUP
    trap '' TERM              # 下面要 kill 整个进程组,别把自己打断
    echo ""
    echo "🛑 停止所有服务…"

    run_guard_sweep_ports -TERM

    # 整个进程组一次搞定:等两个直接子进程是不够的,真正占着 dashboard 端口的是
    # npm 派生出来的 next-server。
    #
    # 但只在我们**是组长**时才这么做。交互终端里每次启动都是独立的进程组,没问题;
    # 而在没有作业控制的环境(CI、被别的脚本调用)里,我们可能和调用方共用一个组——
    # 那时 kill 整个组会打到无关进程。实测过:两次连续启动共用进程组时,第一次的
    # 清理把第二次刚起好的实例一起干掉了。
    if [ "$$" = "$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')" ]; then
        kill -TERM -$$ 2>/dev/null || true
    fi
    sleep 1
    run_guard_sweep_ports -KILL

    # 告诉看门狗:已经正常收尾了,不用再兜底。否则它还要空转十几秒,期间 pgrep 会
    # 看到一个命令行同为 start-all.sh 的子 shell,看起来像没清干净。
    : > "$RUN_GUARD_DIR/$$.done" 2>/dev/null || true
    rm -f "$RUN_GUARD_DIR"/api.pid "$RUN_GUARD_DIR"/dashboard.pid \
          "$RUN_GUARD_DIR"/session.pid "$RUN_GUARD_DIR/$$.children" 2>/dev/null || true

    echo "✅ 所有服务已停止"
    exit $exit_code
}

# 最后一道:一个活得比本脚本久的轮询进程。脚本被 SIGKILL 时 trap 不会运行,而那正是
# 产生孤儿的场景。
run_guard_watchdog() {
    local main_pid=$$ ports="$RUN_GUARD_PORTS" dir="$RUN_GUARD_DIR"
    local pattern="$RUN_GUARD_PATTERN"
    (
        # 启动脚本用了 set -e,子 shell 会继承。清理时对一个已经退出的进程 kill 会
        # 返回非零,errexit 就把看门狗自己终止了——实测:它在真正动手前就退出,孤儿
        # 一个没清掉。收尾逻辑必须能容忍失败。
        set +e

        # 归属判定不能等到父进程死后再做:``npm run dev`` 会先于它派生的 node /
        # next-server 退出,链一断,ppid 就指向一个已经不存在的进程,谁是谁的后代就
        # 查不出来了(实测:next-server 因此活了下来)。
        #
        # 所以在会话还活着的时候**持续快照它的后代树**。父进程一死,最后一张快照就是
        # 完整的归属清单——按清单杀,既不会漏掉孙进程,也不可能碰到别的会话。
        local snapshot="" pid ppid line
        while kill -0 "$main_pid" 2>/dev/null; do
            snapshot=$(
                ps -eo pid=,ppid= 2>/dev/null | awk -v root="$main_pid" '
                    { parent[$1] = $2; pids[NR] = $1 }
                    END {
                        for (i = 1; i <= NR; i++) {
                            p = pids[i]; hops = 0
                            while (p != "" && p != "1" && p != "0" && hops < 64) {
                                if (p == root) { print pids[i]; break }
                                p = parent[p]; hops++
                            }
                        }
                    }'
            )
            sleep 2
        done
        sleep 3                      # 先让正常的 cleanup 有机会跑完
        if [ -f "$dir/$main_pid.done" ]; then
            rm -f "$dir/$main_pid.done" "$dir/$main_pid.children" 2>/dev/null
            exit 0                   # 已经正常收尾,兜底无事可做
        fi

        local round targets="$snapshot"
        [ -f "$dir/$main_pid.children" ] && \
            targets="$targets $(cat "$dir/$main_pid.children" 2>/dev/null)"

        # 看门狗自己也是这个脚本的子 shell,命令行同样是 start-all.sh,会匹配上
        # $pattern。不排除的话它第一轮就把自己杀了,清理半途而废——实测正是如此:
        # API 和 next-server 都活了下来。
        #
        # 不能用 $BASHPID:macOS 自带的是 bash 3.2,那个变量 4.0 才有,取出来是空字符串,
        # 于是排除条件永远不成立。起一个 sh 子进程问它的 PPID,在 3.2 上也work。
        local self
        self=$(sh -c 'echo $PPID')

        for round in 1 2; do
            for pid in $targets; do
                [ -n "$pid" ] || continue
                [ "$pid" = "$self" ] && continue
                [ "$pid" = "$main_pid" ] && continue
                kill -0 "$pid" 2>/dev/null || continue
                # 命令行仍要比对:pid 会被系统回收复用,快照可能已经过期。
                ps -o command= -p "$pid" 2>/dev/null | grep -qE "$pattern" || continue
                [ "$round" = 1 ] && kill -TERM "$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
            done
            sleep 3
        done
        rm -f "$dir/$main_pid.children" 2>/dev/null
    ) >/dev/null 2>&1 &
    disown $! 2>/dev/null || true
}

run_guard_arm() {
    RUN_GUARD_ARMED=1
    trap run_guard_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP        # 关终端发的就是这个 — 之前漏的正是它
    run_guard_watchdog
}
