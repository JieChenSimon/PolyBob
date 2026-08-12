# Python Environment Integrity

## Scope

适用于 PolyBob 的 Python 依赖声明、开发环境、CI、容器和运行文档；不适用于独立参考仓库 `Kronos/`。

## Hard Acceptance Criteria

- `pyproject.toml` 是直接依赖的唯一声明源，`uv.lock` 是可复现解析的唯一锁文件。
- Python 版本固定为 3.11；本地环境固定为项目内 `.venv`。
- 新环境必须能用 `uv sync --locked` 建立，常规命令必须通过 `uv run --locked` 执行。
- 运行依赖与开发依赖分离；Docker 只能安装锁定的运行依赖，CI 必须安装锁定的开发依赖。
- 迁移不得删除 Conda 环境中实际使用但未声明的运行依赖。
- 每个直接运行依赖必须有静态导入、受测动态导入或外部子进程调用证据；不得依赖其他包
  偶然传递安装直接使用的包，也不得保留没有运行或验证用途的开发工具。
- 完整 Python 测试、API 启动烟测和 dashboard 构建必须通过。

## Rejection Conditions

- 存在活跃的 `environment.yml`、`requirements*.txt` 或文档要求 Conda，形成第二依赖事实源。
- CI 或 Docker 绕过 `uv.lock`，或使用未锁定的 `pip install`。
- 只能从源码根目录导入、隔离安装后缺失运行模块。
- 以升级依赖或改变运行行为冒充环境迁移。

## Validation

运行 `uv lock --check`、`uv sync --locked`、`uv run --locked pytest -q`、API 启动烟测、
dashboard 测试与构建，并检查活跃文件中不再存在 Conda 工作流。
