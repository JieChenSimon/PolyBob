from datetime import datetime, timedelta

import pytest

from modules.onchain_monitor.service import OnchainMonitorService
from libs.schemas import OnchainEntityType, OnchainWatchAddress


@pytest.mark.asyncio
async def test_cex_transfer_generates_alert():
    service = OnchainMonitorService(
        watches=[
            OnchainWatchAddress(
                watch_id="rave_deployer",
                chain="ethereum",
                token_symbol="RAVE",
                contract_address="0x1111",
                address="0xaaaa",
                label="RAVE deployer",
                entity_type=OnchainEntityType.DEPLOYER,
                cex_transfer_threshold_usd=50000,
            )
        ],
        cex_addresses={"0xdddd": {"label": "binance_hot_wallet_sample", "exchange": "binance"}},
    )

    result = await service.ingest_event(
        {
            "chain": "ethereum",
            "tx_hash": "0xtx1",
            "block_time": datetime.utcnow().isoformat(),
            "token_symbol": "RAVE",
            "contract_address": "0x1111",
            "from_address": "0xaaaa",
            "to_address": "0xdddd",
            "amount": 100000,
            "usd_value": 80000,
        }
    )

    assert result["alert_count"] == 1
    assert result["alerts"][0]["alert_type"] == "cex_transfer"


@pytest.mark.asyncio
async def test_clustered_cex_transfers_generate_distribution_cluster_alert():
    service = OnchainMonitorService(
        watches=[
            OnchainWatchAddress(
                watch_id="aria_team",
                chain="base",
                token_symbol="ARIA",
                contract_address="0x2222",
                address="0xcccc",
                label="ARIA team multisig",
                entity_type=OnchainEntityType.TEAM,
                cex_transfer_threshold_usd=40000,
            )
        ],
        cex_addresses={"0xeeee": {"label": "okx_deposit_wallet_sample", "exchange": "okx"}},
        cluster_window_minutes=90,
    )

    first_time = datetime.utcnow() - timedelta(minutes=10)
    second_time = datetime.utcnow()

    await service.ingest_event(
        {
            "event_id": "evt_1",
            "chain": "base",
            "tx_hash": "0xtx2",
            "block_time": first_time.isoformat(),
            "token_symbol": "ARIA",
            "contract_address": "0x2222",
            "from_address": "0xcccc",
            "to_address": "0xeeee",
            "amount": 50000,
            "usd_value": 45000,
        }
    )

    result = await service.ingest_event(
        {
            "event_id": "evt_2",
            "chain": "base",
            "tx_hash": "0xtx3",
            "block_time": second_time.isoformat(),
            "token_symbol": "ARIA",
            "contract_address": "0x2222",
            "from_address": "0xcccc",
            "to_address": "0xeeee",
            "amount": 70000,
            "usd_value": 50000,
        }
    )

    alert_types = {alert["alert_type"] for alert in result["alerts"]}
    assert "cex_transfer" in alert_types
    assert "distribution_cluster" in alert_types
    assert service.get_summary()["critical_alerts"] >= 1


@pytest.mark.asyncio
async def test_staging_wallet_then_cex_generates_staging_alert():
    service = OnchainMonitorService(
        watches=[
            OnchainWatchAddress(
                watch_id="rave_treasury",
                chain="ethereum",
                token_symbol="RAVE",
                contract_address="0x1111",
                address="0xbbbb",
                label="RAVE treasury",
                entity_type=OnchainEntityType.TREASURY,
                staging_transfer_threshold_usd=30000,
                cex_transfer_threshold_usd=50000,
            )
        ],
        cex_addresses={"0xdddd": {"label": "binance_hot_wallet_sample", "exchange": "binance"}},
        cluster_window_minutes=90,
    )

    first_time = datetime.utcnow() - timedelta(minutes=25)
    second_time = datetime.utcnow()

    first_result = await service.ingest_event(
        {
            "event_id": "evt_stage_in",
            "chain": "ethereum",
            "tx_hash": "0xstage1",
            "block_time": first_time.isoformat(),
            "token_symbol": "RAVE",
            "contract_address": "0x1111",
            "from_address": "0xbbbb",
            "to_address": "0xffff",
            "amount": 60000,
            "usd_value": 60000,
            "to_entity_type": "fresh_wallet",
        }
    )

    second_result = await service.ingest_event(
        {
            "event_id": "evt_stage_out",
            "chain": "ethereum",
            "tx_hash": "0xstage2",
            "block_time": second_time.isoformat(),
            "token_symbol": "RAVE",
            "contract_address": "0x1111",
            "from_address": "0xffff",
            "to_address": "0xdddd",
            "amount": 59000,
            "usd_value": 59000,
        }
    )

    assert first_result["alert_count"] == 0
    alert_types = {alert["alert_type"] for alert in second_result["alerts"]}
    assert "staging_to_cex" in alert_types
    assert service.get_summary()["pending_staging_wallets"] >= 1
