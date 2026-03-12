# PolyBob 界面使用指南

PolyBob 提供两种界面：Web Dashboard 和 TUI（终端界面）

## 1. Web Dashboard（推荐）

### 特点
- 🎨 赛博朋克终端美学设计
- 📊 实时图表和数据可视化
- ⚠️ 异常市场高亮显示
- 🔄 自动刷新（每5秒）
- 📱 响应式设计

### 安装和启动

```bash
# 1. 进入 dashboard 目录
cd apps/dashboard

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

访问 http://localhost:3001

### 界面说明

#### 顶部导航栏
- 连接状态指示器
- 市场数量
- 最后更新时间
- 系统时间

#### 左侧市场列表
- 显示所有 watchlist 中的市场
- 实时特征数据（中间价、价差、成交量等）
- 异常市场会高亮显示（红色闪烁）
- 点击选择市场查看详情

#### 右侧市场详情
- 关键指标卡片
- 价格历史图表
- 价差分析图表
- 订单簿信息
- 交易活动统计

### 异常告警

系统会自动检测以下异常：
- **价差过大**：spread_bps > 200（红色闪烁）
- **价格跳变**：price_jump_score > 3（红色闪烁）
- **警告级别**：spread_bps > 100 或 price_jump_score > 2（黄色）

### 生产部署

```bash
# 构建生产版本
npm run build

# 启动生产服务器
npm start
```

## 2. TUI（终端界面）

### 特点
- 🖥️ 纯终端界面，无需浏览器
- ⚡ 轻量级，资源占用少
- 🎯 适合服务器环境
- 📊 实时数据表格显示

### 安装依赖

```bash
# 确保已激活 conda 环境
conda activate polybob

# Rich 库已包含在 environment.yml 中
# 如果需要单独安装：
pip install rich
```

### 启动 TUI

```bash
# 从项目根目录运行
python -m apps.tui
```

### 界面说明

#### 顶部状态栏
- 连接状态
- 市场数量
- 最后更新时间

#### 市场列表（左侧）
- 市场 ID
- 中间价（MID）
- 价差（SPREAD）
- 成交量（VOL）
- 状态指示器

#### 市场详情（右侧）
- 完整的市场特征数据
- 订单簿信息
- 交易活动统计

#### 底部控制栏
- `↑/↓` - 导航选择市场
- `Q` - 退出
- `R` - 手动刷新

### 快捷键

- `Ctrl+C` - 退出程序
- 自动每5秒刷新数据

## 3. 同时运行多个界面

你可以同时运行 API、Web Dashboard 和 TUI：

```bash
# 终端 1：启动 API
conda activate polybob
python -m apps.api.main

# 终端 2：启动 Web Dashboard
cd apps/dashboard
npm run dev

# 终端 3：启动 TUI
conda activate polybob
python -m apps.tui
```

## 4. 界面对比

| 特性 | Web Dashboard | TUI |
|------|---------------|-----|
| 图表可视化 | ✅ 丰富的图表 | ❌ 纯文本 |
| 资源占用 | 中等（浏览器） | 低（终端） |
| 交互性 | ✅ 鼠标点击 | ⌨️ 键盘导航 |
| 美观度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 服务器友好 | ❌ 需要浏览器 | ✅ SSH 可用 |
| 实时更新 | ✅ 5秒 | ✅ 5秒 |
| 异常告警 | ✅ 动画效果 | ✅ 颜色标记 |

## 5. 故障排除

### Web Dashboard 无法连接

```bash
# 检查 API 是否运行
curl http://localhost:8000

# 检查端口是否被占用
lsof -i :3001
```

### TUI 显示异常

```bash
# 确保终端支持颜色
echo $TERM

# 尝试设置终端类型
export TERM=xterm-256color
```

### 数据不更新

```bash
# 检查 API 服务状态
curl http://localhost:8000/markets/watchlist

# 查看 API 日志
# 检查是否有错误信息
```

## 6. 推荐使用场景

### 使用 Web Dashboard
- 日常监控和分析
- 需要查看图表和历史数据
- 多市场对比分析
- 演示和展示

### 使用 TUI
- SSH 远程服务器监控
- 资源受限环境
- 快速查看市场状态
- 脚本自动化集成

## 7. 下一步

- 查看 [API 文档](http://localhost:8000/docs)
- 阅读 [开发指南](DEVELOPMENT.md)
- 自定义界面主题和配置
