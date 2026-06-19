"""
Broker Ext 测试 — 不触发网络请求
"""
import sys
import types
import logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

print("=" * 50)
print("  Broker Ext 测试")
print("=" * 50)

# ===== 模拟 AlpacaBroker =====
mock_config = {
    "name": "Mock Alpaca",
    "type": "alpaca",
    "paper": True,
    "env_key_id": "TEST_KEY",
    "env_secret": "TEST_SECRET",
    "base_url": "https://paper-api.alpaca.markets",
    "data_url": "https://data.alpaca.markets",
}

class MockBroker:
    """模拟 AlpacaBroker"""
    def __init__(self):
        self.key = "test_key"
        self.secret = "test_secret"
        self.base = mock_config["base_url"]

    def get_account(self):
        return {"equity": 10000, "cash": 5000, "buying_power": 20000}

    def get_positions(self):
        return [
            {"symbol": "AAPL", "qty": 10, "market_value": 1800,
             "cost_basis": 1700, "current_price": 180, "pnl": 100, "pnl_pct": 5.88},
        ]

    def get_latest_trade(self, sym):
        raise AttributeError("这个方法不存在")

    def submit_order(self, symbol, qty, side, order_type="market"):
        return {"order_id": "mock-123", "symbol": symbol, "qty": qty}

# 手动加载 _wrap_alpaca 函数
from broker_ext import _wrap_alpaca

broker = MockBroker()
wrapped = _wrap_alpaca(broker, mock_config)

# === 测试扩展方法是否已绑定 ===
assert hasattr(wrapped, "get_portfolio_summary"), "get_portfolio_summary 未绑定"
assert hasattr(wrapped, "get_latest_price"), "get_latest_price 未绑定"
assert hasattr(wrapped, "get_bars"), "get_bars 未绑定"
assert hasattr(wrapped, "submit_limit_order"), "submit_limit_order 未绑定"
assert hasattr(wrapped, "format_error"), "format_error 未绑定"
print("✅ 5个扩展方法全部绑定")

# === 测试 get_portfolio_summary ===
summary = wrapped.get_portfolio_summary()
assert summary["equity"] == 10000
assert summary["position_count"] == 1
assert summary["total_pnl"] == 100
assert summary["exposure_pct"] == 18.0
print(f"✅ get_portfolio_summary: equity=${summary['equity']}, "
      f"positions={summary['position_count']}, exposure={summary['exposure_pct']}%")

# === 测试 format_error ===
err_msg = wrapped.format_error({"error": "insufficient funds"})
assert "insufficient funds" in err_msg
print(f"✅ format_error: {err_msg}")

err_msg2 = wrapped.format_error(ValueError("bad request"))
assert "bad request" in err_msg2
print(f"✅ format_error (exception): {err_msg2}")

# === 测试 get_broker 入口 ===
# 用 mock 模拟完整链路
from broker_ext import get_broker
# 只是测试 import 没问题
print("✅ get_broker 导入成功")

# === 测试 compare_brokers ===
from broker_ext import compare_brokers
print("✅ compare_brokers 导入成功")

# === 测试 get_account_summary ===
from broker_ext import get_account_summary
print("✅ get_account_summary 导入成功")

# === 测试 get_price ===
from broker_ext import get_price
print("✅ get_price 导入成功")

print()
print("=" * 50)
print("  ✅ 全部测试通过!")
print("=" * 50)
