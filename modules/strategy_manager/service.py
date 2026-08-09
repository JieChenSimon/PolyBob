"""
Strategy Manager Service - 策略管理服务

职责:
- 维护策略模板注册表
- 管理策略实例生命周期
- 为 API 和控制面提供统一视图
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import uuid

import structlog
import yaml

from libs.events import get_event_bus, Topics
from strategies.ai_enhanced_prediction_v1 import AIEnhancedPredictionV1
from strategies.altcoin_retail_crowding import AltcoinRetailCrowding
from strategies.cross_market_dislocation_v1 import CrossMarketDislocationV1
from strategies.spread_arbitrage_v1 import SpreadArbitrageV1
from strategies.spread_reversion_v1 import SpreadReversionV1
from strategies.us_insider_cluster_buy import UsInsiderClusterBuy

logger = structlog.get_logger()


StrategyFactory = Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass
class StrategyTemplateRecord:
    strategy_id: str
    name: str
    description: str
    family: str
    config_path: str
    parameters: dict[str, Any]
    risk_limits: dict[str, Any]
    runtime_mode: str = "research"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "family": self.family,
            "status": "template",
            "runtime_mode": self.runtime_mode,
            "parameters": self.parameters,
            "risk_limits": self.risk_limits,
            "source": self.config_path,
            "enabled": self.enabled,
        }


@dataclass
class StrategyInstanceRecord:
    instance_id: str
    strategy_id: str
    name: str
    config: dict[str, Any]
    risk_limits: dict[str, Any]
    status: str = "stopped"
    environment: str = "paper"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    error: str | None = None
    strategy: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "config": self.config,
            "risk_limits": self.risk_limits,
            "status": self.status,
            "environment": self.environment,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_stopped_at": self.last_stopped_at.isoformat() if self.last_stopped_at else None,
            "error": self.error,
        }


class StrategyManagerService:
    """策略管理服务"""

    def __init__(self, strategy_dir: str | Path | None = None, dependencies: dict[str, Any] | None = None):
        self.event_bus = get_event_bus()
        self.strategy_dir = Path(strategy_dir or Path(__file__).parent.parent.parent / "strategies")
        self.dependencies = dependencies or {}
        self.templates: dict[str, StrategyTemplateRecord] = {}
        self.instances: dict[str, StrategyInstanceRecord] = {}
        self._running = False
        self._factories: dict[str, StrategyFactory] = {
            "cross_market_dislocation_v1": lambda config, deps: CrossMarketDislocationV1(config),
            "spread_reversion_v1": lambda config, deps: SpreadReversionV1(config),
            "ai_enhanced_prediction_v1": lambda config, deps: AIEnhancedPredictionV1(config),
            "spread_arbitrage_v1": lambda config, deps: SpreadArbitrageV1(
                config,
                intent_service=deps.get("intent_execution_service"),
            ),
            # The only strategy on this list whose edge cleared the promotion
            # gate on real data. It exists so the board and the desk describe
            # the same object: before it, every approved edge was un-implemented
            # and every runnable strategy was unvalidated.
            "us_insider_cluster_buy": lambda config, deps: UsInsiderClusterBuy(
                config,
                intent_service=deps.get("intent_execution_service"),
            ),
            "altcoin_retail_crowding": lambda config, deps: AltcoinRetailCrowding(
                config,
                intent_service=deps.get("intent_execution_service"),
            ),
        }

    async def start(self):
        """启动服务并加载模板。"""
        logger.info("starting_strategy_manager_service")
        self._running = True
        self._load_templates()
        self._seed_default_instances()

    async def stop(self):
        """停止服务并结束运行中的策略实例。"""
        logger.info("stopping_strategy_manager_service")
        self._running = False

        for instance in list(self.instances.values()):
            if instance.status == "running":
                await self.stop_instance(instance.instance_id)

    def _load_templates(self):
        """从 YAML 模板目录加载策略模板。"""
        self.templates.clear()

        if not self.strategy_dir.exists():
            logger.warning("strategy_dir_missing", path=str(self.strategy_dir))
            return

        for config_path in sorted(self.strategy_dir.glob("*/config.yaml")):
            try:
                with open(config_path, encoding="utf-8") as handle:
                    raw = yaml.safe_load(handle) or {}
            except Exception as exc:
                logger.error("strategy_template_load_failed", path=str(config_path), error=str(exc))
                continue

            strategy_id = str(raw.get("strategy_id") or config_path.parent.name)
            family = self._derive_family(strategy_id)
            runtime_mode = self._derive_runtime_mode(strategy_id)

            self.templates[strategy_id] = StrategyTemplateRecord(
                strategy_id=strategy_id,
                name=str(raw.get("name") or config_path.parent.name),
                description=str(raw.get("description") or ""),
                family=family,
                config_path=str(config_path.relative_to(self.strategy_dir.parent)),
                parameters=dict(raw.get("parameters") or {}),
                risk_limits=dict(raw.get("risk_limits") or {}),
                runtime_mode=runtime_mode,
            )

        logger.info("strategy_templates_loaded", count=len(self.templates))

    def _seed_default_instances(self):
        """为每个模板创建一个默认实例视图。"""
        for template in self.templates.values():
            instance_id = f"{template.strategy_id}:default"
            if instance_id in self.instances:
                continue

            self.instances[instance_id] = StrategyInstanceRecord(
                instance_id=instance_id,
                strategy_id=template.strategy_id,
                name=f"{template.name} / Default",
                config=dict(template.parameters),
                risk_limits=dict(template.risk_limits),
            )

    def _derive_family(self, strategy_id: str) -> str:
        if strategy_id.startswith("cross_market") or "spread" in strategy_id:
            return "arbitrage"
        if strategy_id.startswith("ai_"):
            return "prediction"
        if "insider" in strategy_id:
            return "event_study"
        return strategy_id.replace("_v1", "").split("_")[0]

    def _derive_runtime_mode(self, strategy_id: str) -> str:
        """How far a template is allowed to go, from the promotion board.

        A strategy whose edge cleared the gate on real data is paper-ready; the
        rest stay research whatever their plumbing looks like. Reading this from
        the board rather than from the name keeps the desk and the evidence in
        step — the two had drifted completely apart.
        """
        from libs.quant.promotion_registry import get_registry

        # 只看看板。原来这里还有一条 `"spread" in strategy_id -> paper_ready` 的
        # 名字兜底,等于给一个从未过门禁的策略发通行证——而这个函数的 docstring
        # 说的正是"从看板读而不是从名字读"。名字里有什么字跟它有没有优势无关。
        return "paper_ready" if get_registry().is_promoted(strategy_id) else "research"

    def list_templates(self) -> list[dict[str, Any]]:
        return [template.to_dict() for template in self.templates.values()]

    def get_template(self, strategy_id: str) -> StrategyTemplateRecord | None:
        return self.templates.get(strategy_id)

    def list_instances(self) -> list[dict[str, Any]]:
        return [instance.to_dict() for instance in self.instances.values()]

    def get_instance(self, instance_id: str) -> StrategyInstanceRecord | None:
        return self.instances.get(instance_id)

    async def create_instance(
        self,
        strategy_id: str,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        environment: str = "paper",
    ) -> dict[str, Any]:
        template = self.get_template(strategy_id)
        if template is None:
            raise ValueError(f"Unknown strategy template: {strategy_id}")

        instance_id = f"{strategy_id}:{uuid.uuid4().hex[:8]}"
        merged_config = dict(template.parameters)
        if config:
            merged_config.update(config)

        instance = StrategyInstanceRecord(
            instance_id=instance_id,
            strategy_id=strategy_id,
            name=name or f"{template.name} / {environment}",
            config=merged_config,
            risk_limits=dict(template.risk_limits),
            environment=environment,
        )
        self.instances[instance_id] = instance

        await self.event_bus.publish(
            Topics.STRATEGY_INSTANCE_CREATED,
            {"instance_id": instance_id, "strategy_id": strategy_id, "environment": environment},
        )
        return instance.to_dict()

    async def start_instance(self, instance_id: str) -> dict[str, Any]:
        instance = self._require_instance(instance_id)
        if instance.status == "running":
            return instance.to_dict()

        factory = self._factories.get(instance.strategy_id)
        if factory is None:
            raise ValueError(f"No strategy factory registered for {instance.strategy_id}")

        strategy = factory(dict(instance.config), self.dependencies)
        await strategy.start()

        instance.strategy = strategy
        instance.status = "running"
        instance.error = None
        instance.last_started_at = datetime.utcnow()
        instance.updated_at = datetime.utcnow()

        await self.event_bus.publish(
            Topics.STRATEGY_INSTANCE_STARTED,
            {"instance_id": instance_id, "strategy_id": instance.strategy_id},
        )
        return instance.to_dict()

    async def stop_instance(self, instance_id: str) -> dict[str, Any]:
        instance = self._require_instance(instance_id)
        if instance.strategy is not None and hasattr(instance.strategy, "stop"):
            await instance.strategy.stop()

        instance.strategy = None
        instance.status = "stopped"
        instance.last_stopped_at = datetime.utcnow()
        instance.updated_at = datetime.utcnow()

        await self.event_bus.publish(
            Topics.STRATEGY_INSTANCE_STOPPED,
            {"instance_id": instance_id, "strategy_id": instance.strategy_id},
        )
        return instance.to_dict()

    async def delete_instance(self, instance_id: str) -> None:
        instance = self._require_instance(instance_id)
        if instance.status == "running":
            await self.stop_instance(instance_id)
        del self.instances[instance_id]

        await self.event_bus.publish(
            Topics.STRATEGY_INSTANCE_DELETED,
            {"instance_id": instance_id, "strategy_id": instance.strategy_id},
        )

    def _require_instance(self, instance_id: str) -> StrategyInstanceRecord:
        instance = self.instances.get(instance_id)
        if instance is None:
            raise ValueError(f"Unknown strategy instance: {instance_id}")
        return instance
