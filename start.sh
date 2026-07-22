#!/bin/bash

# PolyBob 启动脚本

set -e

echo "Starting PolyBob..."

# 检查 conda 是否安装
if ! command -v conda &> /dev/null; then
    echo "Error: conda is not installed"
    echo "Please install Miniconda or Anaconda first"
    echo "https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

CONDA_ENV_NAME="${CONDA_ENV_NAME:-${CONDA_DEFAULT_ENV:-polybob}}"
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
if lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Error: API port $API_PORT is already in use:"
    lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN
    echo "Set POLYBOB_API_PORT to a free port."
    exit 1
fi

echo "Starting API server at http://localhost:$API_PORT..."
POLYBOB_API_PORT="$API_PORT" python -m apps.api.main
