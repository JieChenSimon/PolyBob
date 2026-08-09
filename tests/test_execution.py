"""执行引擎测试"""
import asyncio

from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
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
