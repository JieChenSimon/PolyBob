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

# 检查 conda 环境是否存在
if ! conda env list | grep -q "^polybob "; then
    echo "Creating conda environment 'polybob'..."
    conda env create -f environment.yml
fi

# 激活 conda 环境
echo "Activating conda environment 'polybob'..."
eval "$(conda shell.bash hook)"
conda activate polybob

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please edit .env file with your configuration"
    exit 1
fi

# 启动服务
echo "Starting API server..."
python -m apps.api.main
