FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml .
COPY libs/ libs/
COPY services/ services/
COPY apps/ apps/
COPY strategies/ strategies/

# 安装 Python 依赖
RUN pip install --no-cache-dir -e .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "apps.api.main"]
