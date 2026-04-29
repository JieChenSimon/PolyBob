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

# 启动服务
echo "🧹 Cleaning up port 8000..."
lsof -ti:8000 | xargs -r kill -9 2>/dev/null || true
sleep 1

echo "Starting API server..."
python -m apps.api.main
