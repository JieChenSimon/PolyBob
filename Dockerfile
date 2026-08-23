FROM python:3.11-slim

# Pinned uv keeps dependency installation reproducible across image rebuilds.
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install locked runtime dependencies first so source-only changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# 复制项目文件
COPY libs/ libs/
COPY modules/ modules/
COPY apps/ apps/
COPY strategies/ strategies/
COPY tasks/ tasks/
COPY config/ config/
COPY data/ data/

# Production installs are immutable rather than editable.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# 暴露端口
EXPOSE 18000

# 启动命令
CMD ["python", "-m", "apps.api.main"]
