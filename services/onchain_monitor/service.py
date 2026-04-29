"""Onchain distribution monitor - 监控部署/金库地址的卖出和转入 CEX 行为"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
import uuid

import structlog
import yaml

from libs.events import Topics, get_event_bus
from libs.schemas import (
    DistributionAlert,
    OnchainEntityType,
    OnchainTransferEvent,
    OnchainWatchAddress,
)

logger = structlog.get_logger()


class OnchainMonitorService:
    """配置驱动的链上出货监控服务。

    这一层只负责统一 watchlist、标准化事件和告警规则，不绑定具体数据源。
    后续可以通过 indexer、第三方 API 或自建解析器把事件送进来。
    """

    def __init__(
        self,
        watches: Iterable[OnchainWatchAddress],
        cex_addresses: dict[str, dict] | None = None,
        cluster_window_minutes: int = 60,
    ):
        self.event_bus = get_event_bus()
        self._running = False
        self.cluster_window = timedelta(minutes=cluster_window_minutes)
        self.watches = list(watches)
        self.address_index = {watch.address.lower(): watch for watch in self.watches}
        self.cex_addresses = {
            address.lower(): details for address, details in (cex_addresses or {}).items()
        }
        self.events: dict[str, OnchainTransferEvent] = {}
        self.event_feed: deque[OnchainTransferEvent] = deque(maxlen=500)
        self.alerts: deque[DistributionAlert] = deque(maxlen=300)
        self.address_event_window: dict[str, deque[OnchainTransferEvent]] = defaultdict(deque)
        self.pending_staging_routes: dict[str, deque[dict]] = defaultdict(deque)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "OnchainMonitorService":
        config_path = Path(path)
        if not config_path.exists():
            return cls(watches=[])

        with open(config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        watches: list[OnchainWatchAddress] = []
        for token in raw.get("tokens", []):
            chain = str(token.get("chain", "unknown"))
            token_symbol = str(token.get("token_symbol", "UNKNOWN"))
            contract_address = str(token.get("contract_address", ""))
            defaults = token.get("thresholds", {}) or {}
            for item in token.get("watch_addresses", []):
                entity_value = str(item.get("entity_type", "unknown"))
                try:
                    entity_type = OnchainEntityType(entity_value)
                except ValueError:
                    entity_type = OnchainEntityType.UNKNOWN
                watches.append(
                    OnchainWatchAddress(
                        watch_id=str(item["watch_id"]),
                        chain=chain,
                        token_symbol=token_symbol,
                        contract_address=contract_address,
                        address=str(item["address"]).lower(),
                        label=str(item.get("label", item["watch_id"])),
                        entity_type=entity_type,
                        tags=[str(tag) for tag in item.get("tags", [])],
                        sell_threshold_usd=float(
                            item.get(
                                "sell_threshold_usd",
                                defaults.get("sell_threshold_usd", 25000.0),
                            )
                        ),
                        cex_transfer_threshold_usd=float(
                            item.get(
                                "cex_transfer_threshold_usd",
                                defaults.get("cex_transfer_threshold_usd", 50000.0),
                            )
                        ),
                        staging_transfer_threshold_usd=float(
                            item.get(
                                "staging_transfer_threshold_usd",
                                defaults.get("staging_transfer_threshold_usd", 40000.0),
                            )
                        ),
                    )
                )

        cex_addresses = {
            str(item["address"]).lower(): {
                "label": str(item.get("label", "unknown_cex")),
                "exchange": str(item.get("exchange", "unknown")),
            }
            for item in raw.get("cex_addresses", [])
        }

        return cls(
            watches=watches,
            cex_addresses=cex_addresses,
            cluster_window_minutes=int(raw.get("cluster_window_minutes", 60)),
        )

    async def start(self):
        logger.info("starting_onchain_monitor", watch_count=len(self.watches))
        self._running = True

    async def stop(self):
        logger.info("stopping_onchain_monitor")
        self._running = False

    def list_watch_addresses(self) -> list[dict]:
        return [watch.model_dump(mode="json") for watch in self.watches]

    def list_alerts(self, limit: int = 50) -> list[dict]:
        return [alert.model_dump(mode="json") for alert in list(self.alerts)[-limit:]][::-1]

    def list_events(self, limit: int = 50) -> list[dict]:
        return [event.model_dump(mode="json") for event in list(self.event_feed)[-limit:]][::-1]

    def get_summary(self) -> dict:
        recent_cutoff = datetime.utcnow() - self.cluster_window
        recent_events = [
            event
            for event in self.events.values()
            if event.block_time >= recent_cutoff and event.to_entity_type == OnchainEntityType.CEX
        ]
        recent_cex_flow_usd = sum(event.usd_value for event in recent_events)
        critical_alerts = sum(1 for alert in self.alerts if alert.severity == "critical")
        pending_staging_wallets = self._count_pending_staging_wallets(recent_cutoff)
        pending_staging_value = self._sum_pending_staging_value(recent_cutoff)

        return {
            "watched_addresses": len(self.watches),
            "watched_tokens": len({watch.contract_address for watch in self.watches}),
            "alert_count": len(self.alerts),
            "critical_alerts": critical_alerts,
            "recent_cex_flow_usd": recent_cex_flow_usd,
            "pending_staging_wallets": pending_staging_wallets,
            "pending_staging_value_usd": pending_staging_value,
            "cluster_window_minutes": int(self.cluster_window.total_seconds() / 60),
            "cex_labels": sorted(
                {
                    str(details.get("label", "unknown_cex"))
                    for details in self.cex_addresses.values()
                }
            ),
        }

    async def ingest_event(self, payload: dict | OnchainTransferEvent) -> dict:
        event = payload if isinstance(payload, OnchainTransferEvent) else self._build_event(payload)
        self.events[event.event_id] = event
        self.event_feed.append(event)
        await self.event_bus.publish(Topics.ONCHAIN_TRANSFER_INGESTED, event.model_dump(mode="json"))

        generated_alerts = await self._evaluate_event(event)
        return {
            "event": event.model_dump(mode="json"),
            "alerts": [alert.model_dump(mode="json") for alert in generated_alerts],
            "alert_count": len(generated_alerts),
        }

    def _build_event(self, payload: dict) -> OnchainTransferEvent:
        to_address = str(payload["to_address"]).lower()
        cex_info = self.cex_addresses.get(to_address)

        try:
            to_entity_type = OnchainEntityType(str(payload.get("to_entity_type", "unknown")))
        except ValueError:
            to_entity_type = OnchainEntityType.UNKNOWN

        if cex_info:
            to_entity_type = OnchainEntityType.CEX

        block_time = payload.get("block_time")
        if isinstance(block_time, str):
            block_time = datetime.fromisoformat(block_time.replace("Z", "+00:00")).replace(tzinfo=None)
        elif not isinstance(block_time, datetime):
            block_time = datetime.utcnow()

        return OnchainTransferEvent(
            event_id=str(payload.get("event_id", f"evt_{uuid.uuid4().hex[:12]}")),
            chain=str(payload["chain"]),
            tx_hash=str(payload["tx_hash"]),
            block_time=block_time,
            token_symbol=str(payload["token_symbol"]),
            contract_address=str(payload["contract_address"]),
            from_address=str(payload["from_address"]).lower(),
            to_address=to_address,
            amount=float(payload["amount"]),
            usd_value=float(payload.get("usd_value", 0.0)),
            from_label=payload.get("from_label"),
            to_label=str(payload.get("to_label") or (cex_info or {}).get("label") or ""),
            to_entity_type=to_entity_type,
            action=payload.get("action"),
            source=str(payload.get("source", "manual_ingest")),
        )

    async def _evaluate_event(self, event: OnchainTransferEvent) -> list[DistributionAlert]:
        watch = self.address_index.get(event.from_address.lower())

        alerts: list[DistributionAlert] = []
        if watch is not None:
            self.address_event_window[watch.watch_id].append(event)
            self._trim_event_window(watch.watch_id, event.block_time)
            if self._is_direct_sell(event, watch):
                alerts.append(
                    self._create_alert(
                        watch=watch,
                        event=event,
                        alert_type="direct_sell",
                        severity="critical",
                        title=f"{watch.token_symbol} direct sell detected",
                        summary=f"{watch.label} sold or routed tokens into DEX liquidity.",
                        counterparty=event.to_label or event.to_address,
                    )
                )

            if self._is_cex_transfer(event, watch):
                alerts.append(
                    self._create_alert(
                        watch=watch,
                        event=event,
                        alert_type="cex_transfer",
                        severity="high",
                        title=f"{watch.token_symbol} transfer to CEX",
                        summary=f"{watch.label} moved a large tranche toward a monitored CEX deposit address.",
                        counterparty=event.to_label or event.to_address,
                    )
                )

            self._record_staging_candidate(event, watch)

            cluster_alert = self._build_cluster_alert(watch)
            if cluster_alert is not None:
                alerts.append(cluster_alert)

        staging_alert = self._build_staging_exit_alert(event)
        if staging_alert is not None:
            alerts.append(staging_alert)

        for alert in alerts:
            self.alerts.append(alert)
            await self.event_bus.publish(Topics.ONCHAIN_DISTRIBUTION_ALERT, alert.model_dump(mode="json"))

        return alerts

    def _trim_event_window(self, watch_id: str, now: datetime):
        window = self.address_event_window[watch_id]
        cutoff = now - self.cluster_window
        while window and window[0].block_time < cutoff:
            window.popleft()
        for staging_wallet, routes in list(self.pending_staging_routes.items()):
            while routes and routes[0]["block_time"] < cutoff:
                routes.popleft()
            if not routes:
                self.pending_staging_routes.pop(staging_wallet, None)

    def _is_direct_sell(self, event: OnchainTransferEvent, watch: OnchainWatchAddress) -> bool:
        if event.usd_value < watch.sell_threshold_usd:
            return False
        if event.action in {"sell", "swap_sell"}:
            return True
        return event.to_entity_type in {OnchainEntityType.DEX_POOL, OnchainEntityType.DEX_ROUTER}

    def _is_cex_transfer(self, event: OnchainTransferEvent, watch: OnchainWatchAddress) -> bool:
        return (
            event.to_entity_type == OnchainEntityType.CEX
            and event.usd_value >= watch.cex_transfer_threshold_usd
        )

    def _record_staging_candidate(self, event: OnchainTransferEvent, watch: OnchainWatchAddress):
        if event.usd_value < watch.staging_transfer_threshold_usd:
            return
        if event.to_entity_type in {
            OnchainEntityType.CEX,
            OnchainEntityType.DEX_POOL,
            OnchainEntityType.DEX_ROUTER,
            OnchainEntityType.BRIDGE,
        }:
            return

        routes = self.pending_staging_routes[event.to_address.lower()]
        duplicate = next(
            (
                route for route in routes
                if route["source_event_id"] == event.event_id
            ),
            None,
        )
        if duplicate is not None:
            return

        routes.append(
            {
                "watch_id": watch.watch_id,
                "watch_label": watch.label,
                "watch_address": watch.address,
                "token_symbol": watch.token_symbol,
                "chain": watch.chain,
                "contract_address": watch.contract_address,
                "source_event_id": event.event_id,
                "staging_wallet": event.to_address.lower(),
                "usd_value": event.usd_value,
                "block_time": event.block_time,
                "tx_hash": event.tx_hash,
            }
        )

    def _build_staging_exit_alert(self, event: OnchainTransferEvent) -> DistributionAlert | None:
        if event.to_entity_type != OnchainEntityType.CEX:
            return None

        routes = self.pending_staging_routes.get(event.from_address.lower())
        if not routes:
            return None

        matched_route = next(
            (
                route
                for route in reversed(routes)
                if route["token_symbol"] == event.token_symbol
                and route["chain"] == event.chain
                and route["contract_address"] == event.contract_address
                and event.block_time >= route["block_time"]
            ),
            None,
        )
        if matched_route is None:
            return None

        watch = next(
            (item for item in self.watches if item.watch_id == matched_route["watch_id"]),
            None,
        )
        if watch is None:
            return None

        route_signature = f"{matched_route['source_event_id']}|{event.event_id}"
        existing = next(
            (
                alert
                for alert in reversed(self.alerts)
                if alert.watch_id == watch.watch_id
                and alert.alert_type == "staging_to_cex"
                and alert.metadata.get("route_signature") == route_signature
            ),
            None,
        )
        if existing is not None:
            return None

        combined_value = min(float(matched_route["usd_value"]), event.usd_value)
        return DistributionAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:12]}",
            watch_id=watch.watch_id,
            chain=watch.chain,
            token_symbol=watch.token_symbol,
            contract_address=watch.contract_address,
            address=watch.address,
            label=watch.label,
            alert_type="staging_to_cex",
            severity="critical",
            title=f"{watch.token_symbol} staged transfer reached CEX",
            summary=f"{watch.label} first routed funds into a staging wallet and that wallet later sent tokens into CEX.",
            usd_value=combined_value,
            event_ids=[matched_route["source_event_id"], event.event_id],
            counterparty=event.to_label or event.to_address,
            created_at=datetime.utcnow(),
            metadata={
                "route_signature": route_signature,
                "staging_wallet": event.from_address.lower(),
                "origin_tx_hash": str(matched_route["tx_hash"]),
                "exit_tx_hash": event.tx_hash,
                "source": event.source,
            },
        )

    def _build_cluster_alert(self, watch: OnchainWatchAddress) -> DistributionAlert | None:
        window = self.address_event_window[watch.watch_id]
        cex_events = [event for event in window if event.to_entity_type == OnchainEntityType.CEX]
        if len(cex_events) < 2:
            return None

        total_cex_value = sum(event.usd_value for event in cex_events)
        if total_cex_value < (watch.cex_transfer_threshold_usd * 1.5):
            return None

        latest_event = cex_events[-1]
        signature = "|".join(event.event_id for event in cex_events[-3:])
        existing = next(
            (
                alert
                for alert in reversed(self.alerts)
                if alert.watch_id == watch.watch_id
                and alert.alert_type == "distribution_cluster"
                and alert.metadata.get("signature") == signature
            ),
            None,
        )
        if existing is not None:
            return None

        return DistributionAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:12]}",
            watch_id=watch.watch_id,
            chain=watch.chain,
            token_symbol=watch.token_symbol,
            contract_address=watch.contract_address,
            address=watch.address,
            label=watch.label,
            alert_type="distribution_cluster",
            severity="critical",
            title=f"{watch.token_symbol} clustered CEX distribution",
            summary=f"{watch.label} sent multiple transfers toward CEX within the monitoring window.",
            usd_value=total_cex_value,
            event_ids=[event.event_id for event in cex_events],
            counterparty="multiple_cex_wallets",
            created_at=datetime.utcnow(),
            metadata={
                "window_minutes": str(int(self.cluster_window.total_seconds() / 60)),
                "signature": signature,
            },
        )

    def _create_alert(
        self,
        *,
        watch: OnchainWatchAddress,
        event: OnchainTransferEvent,
        alert_type: str,
        severity: str,
        title: str,
        summary: str,
        counterparty: str,
    ) -> DistributionAlert:
        return DistributionAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:12]}",
            watch_id=watch.watch_id,
            chain=watch.chain,
            token_symbol=watch.token_symbol,
            contract_address=watch.contract_address,
            address=watch.address,
            label=watch.label,
            alert_type=alert_type,
            severity=severity,
            title=title,
            summary=summary,
            usd_value=event.usd_value,
            event_ids=[event.event_id],
            counterparty=counterparty,
            created_at=datetime.utcnow(),
            metadata={
                "tx_hash": event.tx_hash,
                "source": event.source,
            },
        )

    def _count_pending_staging_wallets(self, cutoff: datetime) -> int:
        return sum(
            1
            for routes in self.pending_staging_routes.values()
            if any(route["block_time"] >= cutoff for route in routes)
        )

    def _sum_pending_staging_value(self, cutoff: datetime) -> float:
        total = 0.0
        for routes in self.pending_staging_routes.values():
            recent_routes = [route for route in routes if route["block_time"] >= cutoff]
            if recent_routes:
                total += max(float(route["usd_value"]) for route in recent_routes)
        return total
