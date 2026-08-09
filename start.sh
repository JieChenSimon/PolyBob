#!/bin/bash

# PolyBob 启动脚本

set -e
cd "$(dirname "$0")"

# 同一份进程生命周期保障:关终端 / Ctrl+C / kill -9 之后不留孤儿。
# shellcheck source=scripts/run-guard.sh
. "$(dirname "$0")/scripts/run-guard.sh"

echo "Starting PolyBob..."

# 检查 conda 是否安装
if ! command -v conda &> /dev/null; then
    echo "Error: conda is not installed"
    echo "Please install Miniconda or Anaconda first"
    echo "https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# 用项目自己的环境。原来会回退到 CONDA_DEFAULT_ENV,也就是"你碰巧激活着的那个"——
# 在 base 里跑就 ModuleNotFoundError: structlog。start-all.sh 一直用的是 polybob。
CONDA_ENV_NAME="${CONDA_ENV_NAME:-polybob}"
API_PORT="${POLYBOB_API_PORT:-}"

# 检查 conda 环境是否存在
if ! conda env list | grep -q "^${CONDA_ENV_NAME} "; then
    echo "Error: conda environment '${CONDA_ENV_NAME}' not found"
    echo "Set CONDA_ENV_NAME to an existing environment or create it first"
    exit 1
fi

# 激活 conda 环境
echo "Activating conda environment '${CONDA_ENV_NAME}'..."
eval "$(conda shell.bash hook)"
conda activate "$CONDA_ENV_NAME"

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
POLYBOB_API_PORT="$API_PORT" python -m apps.api.main &
run_guard_write_pid api "$!"
wait
