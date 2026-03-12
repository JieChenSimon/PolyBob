# PolyBob 快速启动指南

## 方式一：本地开发（推荐用于开发）

### 1. 安装依赖

```bash
# 使用 conda 创建环境
conda env create -f environment.yml

# 激活环境
conda activate polybob
```

### 2. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env（可选，使用默认配置也可以运行）
# vim .env
```

### 3. 启动服务

```bash
# 使用启动脚本
./start.sh

# 或直接运行
python -m apps.api.main
```

### 4. 验证服务

```bash
# 健康检查
curl http://localhost:8000

# 查看 API 文档
open http://localhost:8000/docs
```

## 方式二：Docker Compose（推荐用于完整环境）

### 1. 启动所有服务

```bash
# 启动所有服务（API + Postgres + Redis + Prometheus + Grafana）
docker-compose up -d

# 查看日志
docker-compose logs -f api
```

### 2. 访问服务

- API: http://localhost:8000
- API 文档: http://localhost:8000/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

### 3. 停止服务

```bash
docker-compose down

# 删除数据卷
docker-compose down -v
```

## 测试 API

### 获取 Watchlist

```bash
curl http://localhost:8000/markets/watchlist
```

响应示例：
```json
{
  "watchlist": ["market_id_1", "market_id_2"],
  "count": 2
}
```

### 获取市场特征

```bash
curl http://localhost:8000/markets/{market_id}/features
```

响应示例：
```json
{
  "market_id": "0x123...",
  "timestamp": "2024-03-12T10:00:00Z",
  "mid_price": 0.55,
  "spread_bps": 50.0,
  "bid_price": 0.54,
  "ask_price": 0.56,
  "depth_imbalance": 0.1,
  "trade_intensity_1m": 5,
  "volume_1m": 1250.0,
  "price_jump_score": 0.5
}
```

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_events.py -v

# 查看覆盖率
pytest --cov=libs --cov=services --cov-report=html
```

## 开发工作流

### 1. 创建新分支

```bash
git checkout -b feature/my-feature
```

### 2. 开发和测试

```bash
# 启动服务
./start.sh

# 在另一个终端运行测试
pytest

# 代码格式化
black .
ruff check .
```

### 3. 提交代码

```bash
git add .
git commit -m "feat: add my feature"
git push origin feature/my-feature
```

## 常见问题

### Q: 端口被占用？

```bash
# 查看占用端口的进程
lsof -i :8000

# 修改端口（在 apps/api/main.py 中）
uvicorn.run(..., port=8001)
```

### Q: 依赖安装失败？

```bash
# 升级 pip
pip install --upgrade pip

# 清理缓存重新安装
pip cache purge
pip install -e ".[dev]"
```

### Q: WebSocket 连接失败？

检查 Polymarket WebSocket URL 是否可达：
```bash
# 测试连接
wscat -c wss://ws-subscriptions-clob.polymarket.com/ws/market
```

## 下一步

- 阅读 [开发指南](DEVELOPMENT.md)
- 查看 [设计文档](polymarket-realtime-ai-trading-system.md)
- 加入开发讨论

## 获取帮助

- 查看文档：`docs/` 目录
- 提交 Issue
- 联系维护者
