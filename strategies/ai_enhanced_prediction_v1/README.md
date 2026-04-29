# AI Enhanced Prediction Strategy V1

## 策略概述

AI 增强预测策略,使用 Claude API 分析市场特征和问题文本,生成高置信度的交易信号。

## 核心逻辑

1. **特征收集**: 收集实时市场特征(价格、价差、深度、成交量等)
2. **AI 分析**: 将特征和市场问题发送给 Claude API
3. **信号生成**: 基于 AI 分析结果生成结构化交易信号
4. **置信度过滤**: 仅执行高置信度信号

## 参数说明

- `min_confidence`: 最小置信度阈值,默认 0.6
- `signal_ttl_seconds`: 信号有效期(秒),默认 600
- `analysis_interval_seconds`: AI 分析间隔(秒),默认 60

## AI Prompt 设计

策略使用结构化 prompt:
- 市场问题文本
- 实时量化特征
- 要求 JSON 格式输出
- 包含信号方向、置信度、推理和预期优势

## 信号生成

当满足以下条件时生成信号:
- AI 返回 BUY_YES 或 SELL_YES 信号
- 置信度 >= min_confidence
- 成功解析 AI 响应

## 性能优化

- **缓存机制**: 避免重复分析同一市场
- **批处理**: 可扩展为批量分析多个市场
- **速率限制**: 通过 analysis_interval 控制 API 调用频率

## 环境要求

需要设置环境变量:
```bash
ANTHROPIC_API_KEY=your_api_key_here
```

需要安装依赖:
```bash
pip install anthropic
```

## 使用示例

```python
from strategies.ai_enhanced_prediction_v1.strategy import AIEnhancedPredictionV1

config = {
    "min_confidence": 0.6,
    "signal_ttl_seconds": 600,
    "analysis_interval_seconds": 60,
}

strategy = AIEnhancedPredictionV1(config)
await strategy.start()
```

## 成本控制

- 每次分析约消耗 1K tokens
- 默认 60 秒间隔,每市场每小时约 60 次调用
- 建议监控 API 使用量并调整 analysis_interval
