"""Risk Manager 测试"""
import sys
import logging

# 阻止 data_global 在后端被触发
import types
import data_global as _dg_mod
_dg_mod.fetch_stock_data = lambda *a, **kw: None

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from risk_manager import PositionRisk, StopLossManager, CircuitBreaker, RiskManager

print("=" * 50)
print("  风险控制模块测试")
print("=" * 50)

# === 仓位风控 ===
pr = PositionRisk({"max_positions": 10})
ok, msg = pr.within_position_limit(5)
assert ok, f"应在限制内: {msg}"
print("✅ within_position_limit 正常")

ok, msg = pr.within_position_limit(12)
assert not ok, "应超限"
print("✅ within_position_limit 超限检查正常")

# 单票仓位 (默认上限14%)
ok, msg = pr.within_position_pct(10000, 100000)
assert ok, f"应在限制内: {msg}"
ok, msg = pr.within_position_pct(50000, 100000)
assert not ok, "应超限"
print("✅ within_position_pct 正常")

# 仓位计算
qty = pr.calculate_position_size(5.0, 200, 100000)
assert qty > 0, f"仓位应>0, 实际{qty}"
print(f"✅ calculate_position_size: {qty}股 (止损5%, 权益$100k)")

# === 止损管理 ===
sl = StopLossManager({"stop_loss_pct": 15})

# 正常持仓
result = sl.check_position("AAPL", 100, 105, 5.0)
assert not result["should_stop"]
print("✅ 正常持仓不停损")

# 亏损超限
result = sl.check_position("AAPL", 100, 82, -18.0)
assert result["should_stop"]
assert result["action"] == "stop_loss"
print(f"✅ 止损触发: {result['reason']}")

# 浮盈止盈
sl2 = StopLossManager({"stop_loss_pct": 15, "take_profit_pct": 10})
result = sl2.check_position("AAPL", 100, 115, 15.0)
assert result["should_stop"]
assert result["action"] == "take_profit"
print(f"✅ 止盈触发: {result['reason']}")

# === 熔断保护 ===
cb = CircuitBreaker({"circuit_daily_loss": 10})
t, m = cb.check_daily_loss(-5)
assert not t
print("✅ 小亏不熔断")

t, m = cb.check_daily_loss(-15)
assert t
print(f"✅ 大亏熔断: {m}")

# 连续亏损
t, m = cb.check_consecutive_losses([2, -1, -2, -3, -1, -4])
assert t
print(f"✅ 连续亏损熔断: {m}")

# === 统一接口 ===
rm = RiskManager({"stop_loss_pct": 15, "circuit_daily_loss": 10})

signal = {"symbol": "AAPL", "entry_price": 200,
          "position_value": 10000, "total_equity": 100000, "total_active": 3}
ok, msg = rm.check_signal(signal, {})
assert ok
print(f"✅ 信号检查通过: {msg}")

positions = {"TEST": {"qty": 10, "avg_entry": 100, "current_price": 80, "pnl_pct": -20.0}}
stops = rm.check_stops(positions)
assert len(stops) == 1
print(f"✅ 止损检查: {len(stops)}笔触发")

alerts = rm.check_circuit(-15, [1, -2, -3], 12)
assert len(alerts) >= 1
print(f"✅ 熔断检查: {len(alerts)}条告警")

print()
print("=" * 50)
print("  ✅ 全部测试通过!")
print("=" * 50)
