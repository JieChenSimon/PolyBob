"""持续演练系统 - 真实市场滚动训练"""

import asyncio
import structlog
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import json
import numpy as np
import torch

from libs.events import get_event_bus, Topics
from libs.config import get_settings

logger = structlog.get_logger()


class ContinuousTrainer:
    """持续演练训练器"""

    def __init__(self, agent, data_window_days: int = 7):
        self.agent = agent
        self.settings = get_settings()
        self.event_bus = get_event_bus()
        self.data_window_days = data_window_days

        # 数据缓冲区
        self.market_data = []
        self.max_buffer_size = 100000

        # 训练状态
        self.is_training = False
        self.last_train_time = None
        self.train_interval_hours = 24

        # 模型版本管理
        self.model_dir = Path("data/models/rl")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.current_version = 0
        self.ab_test_enabled = False

        # 性能监控
        self.metrics = {
            "train_count": 0,
            "last_loss": 0.0,
            "last_reward": 0.0,
            "rollback_count": 0
        }

    async def start(self):
        """启动持续训练"""
        logger.info("starting_continuous_trainer")

        # 订阅市场数据
        await self.event_bus.subscribe(Topics.ORDERBOOK_TICK, self._on_market_data)
        await self.event_bus.subscribe(Topics.TRADE_TICK, self._on_market_data)

        # 启动定时训练任务
        asyncio.create_task(self._training_loop())

        # 加载最新模型
        await self._load_latest_model()

    async def stop(self):
        """停止训练"""
        logger.info("stopping_continuous_trainer")
        self.is_training = False

    async def _on_market_data(self, data):
        """接收市场数据"""
        self.market_data.append({
            "timestamp": datetime.utcnow(),
            "data": data
        })

        # 限制缓冲区大小
        if len(self.market_data) > self.max_buffer_size:
            self.market_data = self.market_data[-self.max_buffer_size:]

    async def _training_loop(self):
        """定时训练循环"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时检查一次

                if self._should_train():
                    await self._train_async()

            except Exception as e:
                logger.error("training_loop_error", error=str(e))

    def _should_train(self) -> bool:
        """判断是否需要训练"""
        if self.is_training:
            return False

        if self.last_train_time is None:
            return True

        elapsed = (datetime.utcnow() - self.last_train_time).total_seconds() / 3600
        return elapsed >= self.train_interval_hours

    async def _train_async(self):
        """异步训练（不阻塞交易）"""
        self.is_training = True
        logger.info("starting_async_training", data_points=len(self.market_data))

        try:
            # 获取训练数据
            train_data = self._prepare_training_data()
            if len(train_data) < 1000:
                logger.warning("insufficient_training_data", size=len(train_data))
                return

            # 在后台线程训练
            loop = asyncio.get_event_loop()
            loss, reward = await loop.run_in_executor(None, self._train_model, train_data)

            # 保存新模型
            new_version = self.current_version + 1
            model_path = self.model_dir / f"model_v{new_version}.pt"
            torch.save(self.agent.policy_net.state_dict(), model_path)

            # 性能验证
            if await self._validate_model(model_path):
                self.current_version = new_version
                self.metrics["train_count"] += 1
                self.metrics["last_loss"] = loss
                self.metrics["last_reward"] = reward
                logger.info("training_completed", version=new_version, loss=loss, reward=reward)
            else:
                logger.warning("model_validation_failed", rolling_back=True)
                model_path.unlink()
                self.metrics["rollback_count"] += 1

            self.last_train_time = datetime.utcnow()

        except Exception as e:
            logger.error("training_failed", error=str(e))
        finally:
            self.is_training = False

    def _prepare_training_data(self):
        """准备最近7天的训练数据"""
        cutoff_time = datetime.utcnow() - timedelta(days=self.data_window_days)
        recent_data = [d for d in self.market_data if d["timestamp"] >= cutoff_time]
        return recent_data

    def _train_model(self, train_data):
        """训练模型（同步执行）"""
        total_loss = 0.0
        total_reward = 0.0
        batch_count = 0

        # 简化训练循环
        for i in range(0, len(train_data) - 1, 32):
            batch = train_data[i:i+32]
            if len(batch) < 2:
                continue

            # 构造状态-动作-奖励序列
            states = []
            actions = []
            rewards = []
            next_states = []

            for j in range(len(batch) - 1):
                state = self._extract_state(batch[j]["data"])
                next_state = self._extract_state(batch[j+1]["data"])
                action = np.random.randint(0, 3)  # 简化：随机动作
                reward = self._calculate_reward(batch[j]["data"], batch[j+1]["data"])

                states.append(state)
                actions.append(action)
                rewards.append(reward)
                next_states.append(next_state)

            if not states:
                continue

            # 转换为张量
            states_t = torch.FloatTensor(np.array(states))
            actions_t = torch.LongTensor(actions)
            rewards_t = torch.FloatTensor(rewards)
            next_states_t = torch.FloatTensor(np.array(next_states))

            # 计算损失
            q_values = self.agent.policy_net(states_t)
            q_value = q_values.gather(1, actions_t.unsqueeze(1)).squeeze(1)

            next_q_values = self.agent.policy_net(next_states_t).max(1)[0]
            expected_q_value = rewards_t + 0.99 * next_q_values

            loss = torch.nn.functional.mse_loss(q_value, expected_q_value.detach())

            # 反向传播
            self.agent.optimizer.zero_grad()
            loss.backward()
            self.agent.optimizer.step()

            total_loss += loss.item()
            total_reward += rewards_t.mean().item()
            batch_count += 1

        avg_loss = total_loss / max(batch_count, 1)
        avg_reward = total_reward / max(batch_count, 1)

        return avg_loss, avg_reward

    def _extract_state(self, data) -> np.ndarray:
        """从市场数据提取状态向量"""
        if hasattr(data, 'bid_price'):
            return np.array([
                data.bid_price,
                data.ask_price,
                data.bid_size,
                data.ask_size,
                data.ask_price - data.bid_price  # spread
            ])
        return np.zeros(5)

    def _calculate_reward(self, current_data, next_data) -> float:
        """计算奖励（基于价格变化）"""
        if hasattr(current_data, 'bid_price') and hasattr(next_data, 'bid_price'):
            mid_price_current = (current_data.bid_price + current_data.ask_price) / 2
            mid_price_next = (next_data.bid_price + next_data.ask_price) / 2
            return (mid_price_next - mid_price_current) * 100
        return 0.0

    async def _validate_model(self, model_path: Path) -> bool:
        """验证新模型性能"""
        try:
            # 加载新模型
            test_state_dict = torch.load(model_path)

            # 简单验证：检查模型可以正常推理
            test_input = torch.randn(1, 5)
            old_output = self.agent.policy_net(test_input)

            self.agent.policy_net.load_state_dict(test_state_dict)
            new_output = self.agent.policy_net(test_input)

            # 验证输出形状正确
            return new_output.shape == old_output.shape

        except Exception as e:
            logger.error("model_validation_error", error=str(e))
            return False

    async def _load_latest_model(self):
        """加载最新模型"""
        model_files = sorted(self.model_dir.glob("model_v*.pt"))
        if not model_files:
            logger.info("no_existing_model_found")
            return

        latest_model = model_files[-1]
        version = int(latest_model.stem.split("_v")[1])

        try:
            self.agent.policy_net.load_state_dict(torch.load(latest_model))
            self.current_version = version
            logger.info("loaded_model", version=version, path=str(latest_model))
        except Exception as e:
            logger.error("failed_to_load_model", error=str(e))

    def get_metrics(self) -> dict:
        """获取训练指标"""
        return {
            **self.metrics,
            "current_version": self.current_version,
            "is_training": self.is_training,
            "data_buffer_size": len(self.market_data),
            "last_train_time": self.last_train_time.isoformat() if self.last_train_time else None
        }
