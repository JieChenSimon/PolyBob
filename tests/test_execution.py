"""执行引擎测试"""
import asyncio
from decimal import Decimal

from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.db.execution_ledger import ExecutionLedger
from libs.schemas import ExecutionVenue
from modules.execution_engine.basket_executor import BasketExecutor
from modules.execution_engine.contract_executor import ContractExecutor

def test_paper_trading():
    """测试纸上交易"""
    client = BinanceClient(paper_trading=True)
    executor = ContractExecutor(client, paper_trading=True)

    # 测试下单
    order_id = executor.execute_trade("BTCUSDT", "buy", 50000, 0.1)
    assert order_id is not None

    # 测试查询订单
    status = executor.get_order_status(order_id)
    assert status["symbol"] == "BTCUSDT"
    assert status["side"] == "buy"

    # 测试取消订单
    success = executor.cancel_trade(order_id)
    assert success

    print("✓ 纸上交易测试通过")

if __name__ == "__main__":
    test_paper_trading()


def test_basket_executor_submit_and_cancel():
    """测试多腿 basket 执行"""
    executors = {
        ExecutionVenue.BINANCE: ContractExecutor(
            BinanceClient(paper_trading=True),
            paper_trading=True,
            venue=ExecutionVenue.BINANCE.value,
        ),
        ExecutionVenue.HYPERLIQUID: ContractExecutor(
            HyperliquidClient(),
            paper_trading=True,
            venue=ExecutionVenue.HYPERLIQUID.value,
        ),
    }

    basket_executor = BasketExecutor(executors)

    basket = asyncio.run(
        basket_executor.submit_basket(
            parent_intent_id="test_intent",
            legs=[
                {
                    "venue": "binance",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": 0.01,
                    "limit_price": 65000,
                },
                {
                    "venue": "hyperliquid",
                    "symbol": "BTC",
                    "side": "sell",
                    "quantity": 0.01,
                    "limit_price": 65010,
                },
            ],
        )
    )

    assert basket["status"] == "submitted"
    assert len(basket["legs"]) == 2
    assert basket["metrics"]["submitted_legs"] == 2

    cancelled = asyncio.run(basket_executor.cancel_basket(basket["basket_id"]))
    assert cancelled["status"] == "cancelled"


def test_cancel_failure_is_never_reported_as_cancelled():
    executor = ContractExecutor(
        BinanceClient(paper_trading=True),
        paper_trading=True,
        venue=ExecutionVenue.BINANCE.value,
    )
    basket_executor = BasketExecutor({ExecutionVenue.BINANCE: executor})
    basket = asyncio.run(
        basket_executor.submit_basket(
            parent_intent_id="test_intent",
            legs=[
                {
                    "venue": "binance",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": 0.01,
                    "limit_price": 65000,
                }
            ],
        )
    )
    executor.cancel_trade = lambda order_id: False

    result = asyncio.run(basket_executor.cancel_basket(basket["basket_id"]))

    assert result["status"] == "cancel_failed"
    assert result["legs"][0]["status"] == "cancel_failed"
    assert result["legs"][0]["error"] == "venue did not confirm cancellation"


def test_confirmed_fill_is_written_to_canonical_ledger_once(tmp_path):
    ledger = ExecutionLedger(tmp_path / "execution.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    executor = ContractExecutor(
        BinanceClient(paper_trading=True),
        paper_trading=True,
        venue=ExecutionVenue.BINANCE.value,
    )
    basket_executor = BasketExecutor(
        {ExecutionVenue.BINANCE: executor},
        execution_ledger=ledger,
    )

    basket = asyncio.run(
        basket_executor.submit_basket(
            parent_intent_id="test_intent",
            legs=[
                {
                    "venue": "binance",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": 0.01,
                    "limit_price": 65000,
                }
            ],
        )
    )
    order_id = basket["legs"][0]["client_order_id"]
    assert order_id
    assert executor.order_manager.fill_order(order_id)

    reconciled = asyncio.run(basket_executor.reconcile_basket(basket["basket_id"]))

    assert reconciled["status"] == "filled"
    account = ledger.get_account("paper-main")
    assert account.positions["BTCUSDT"].quantity == Decimal("0.01")
    assert ledger.verify_projection("paper-main").consistent is True

    # Recovery/reconciliation is idempotent for the same explicit venue fill.
    asyncio.run(basket_executor.reconcile_basket(basket["basket_id"]))
    assert ledger.get_account("paper-main").positions["BTCUSDT"].quantity == Decimal("0.01")
