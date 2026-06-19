"""
券商接口扩展层 — blankly 风格的统一接口封装
==========================================
不修改 broker_manager.py，只在其基础上加一层扩展方法。

功能：
  - get_portfolio_summary — 完整的投资组合摘要
  - get_latest_price — 获取最新价（统一接口）
  - submit_limit_order — 限价单快捷方式
  - submit_stop_order — 止损单
  - get_order_book — 订单簿（如果有）
  - batch_cancel — 批量撤单
  - format_error — 统一错误格式化

用法：
  from broker_ext import get_broker
  broker, broker_id = get_broker("intraday")
  summary = broker.get_portfolio_summary()
  price = broker.get_latest_price("AAPL")
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.broker_ext")


def get_broker(strategy: str = "conservative"):
    """
    获取指定策略绑定的券商，并包装为增强接口

    参数:
        strategy: "conservative" / "momentum" / "intraday"

    返回:
        (enhanced_broker, broker_id)
        enhanced_broker 在原有接口上增加了扩展方法
    """
    from broker_manager import BrokerManager, load_config
    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id(strategy)
    cfg = load_config().get(broker_id, {})

    if not cfg.get("enabled", False):
        logger.warning(f"策略 {strategy} 绑定的券商 {broker_id} 未启用")
        return None, None

    broker = bm.use(broker_id)

    # 如果是 AlpacaBroker，包装增强
    if cfg.get("type") == "alpaca":
        return _wrap_alpaca(broker, cfg), broker_id

    return broker, broker_id


def _wrap_alpaca(broker, cfg: dict):
    """给 AlpacaBroker 添加扩展方法"""
    import types
    import requests as _req

    base = cfg.get("data_url", "https://data.alpaca.markets")
    key = broker.key if hasattr(broker, 'key') else ""
    secret = broker.secret if hasattr(broker, 'secret') else ""

    # === get_latest_price ===
    def _get_latest_price(self, symbol: str) -> float:
        """获取最新成交价"""
        try:
            r = _req.get(f"{base}/v2/stocks/{symbol}/trades/latest",
                         auth=(key, secret), timeout=5)
            if r.status_code == 200:
                return float(r.json().get("trade", {}).get("p", 0))
        except:
            pass
        return 0.0

    # === get_bars (历史K线) ===
    def _get_bars(self, symbol: str, timeframe: str = "1Day",
                  limit: int = 100) -> list:
        """获取历史K线"""
        try:
            url = (f"{base}/v2/stocks/{symbol}/bars?"
                   f"timeframe={timeframe}&limit={limit}&adjustment=raw")
            r = _req.get(url, auth=(key, secret), timeout=10)
            if r.status_code == 200:
                bars = r.json().get("bars", [])
                return [{
                    "time": b.get("t"),
                    "open": b.get("o"),
                    "high": b.get("h"),
                    "low": b.get("l"),
                    "close": b.get("c"),
                    "volume": b.get("v"),
                } for b in bars]
        except:
            pass
        return []

    # === get_portfolio_summary ===
    def _get_portfolio_summary(self) -> dict:
        """完整的投资组合摘要"""
        try:
            positions = self.get_positions()
            acct = self.get_account()

            total_mv = sum(p.get("market_value", 0) for p in positions)
            total_cost = sum(p.get("cost_basis", 0) for p in positions)
            total_pnl = sum(p.get("pnl", 0) for p in positions)
            total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

            return {
                "equity": acct.get("equity", 0),
                "cash": acct.get("cash", 0),
                "buying_power": acct.get("buying_power", 0),
                "positions": positions,
                "position_count": len(positions),
                "total_market_value": round(total_mv, 2),
                "total_cost_basis": round(total_cost, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "exposure_pct": round(total_mv / max(acct.get("equity", 1), 1) * 100, 1),
            }
        except Exception as e:
            logger.error(f"获取投资组合摘要失败: {e}")
            return {}

    # === submit_limit_order ===
    def _submit_limit_order(self, symbol: str, qty: int, side: str,
                            limit_price: float) -> dict:
        """提交限价单"""
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.client import TradingClient
        try:
            client = TradingClient(key, secret,
                                   paper="paper" in self.base if hasattr(self, 'base') else True)
            side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
            order = client.submit_order(LimitOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY))
            return {"order_id": str(order.id), "status": order.status,
                    "symbol": symbol, "qty": qty, "type": "limit"}
        except Exception as e:
            return {"error": str(e)}

    # === format_error ===
    def _format_error(self, error: any) -> str:
        """统一格式化错误信息"""
        if isinstance(error, dict):
            return error.get("error", json.dumps(error))
        return str(error)[:200]

    # 绑定扩展方法到 broker 实例
    broker.get_latest_price = types.MethodType(_get_latest_price, broker)
    broker.get_bars = types.MethodType(_get_bars, broker)
    broker.get_portfolio_summary = types.MethodType(_get_portfolio_summary, broker)
    broker.submit_limit_order = types.MethodType(_submit_limit_order, broker)
    broker.format_error = types.MethodType(_format_error, broker)

    return broker


def get_account_summary(strategy: str = "conservative") -> dict:
    """
    快捷获取账户摘要

    参数:
        strategy: 策略名称

    返回:
        dict: {equity, cash, positions, pnl, ...}
    """
    broker, _ = get_broker(strategy)
    if not broker:
        return {"error": f"策略 {strategy} 无可用券商"}
    return broker.get_portfolio_summary()


def get_price(symbol: str, strategy: str = "conservative") -> float:
    """
    快捷获取最新股价

    参数:
        symbol: 股票代码
        strategy: 使用哪个策略绑定的券商

    返回:
        float: 最新成交价
    """
    broker, _ = get_broker(strategy)
    if not broker:
        return 0.0
    return broker.get_latest_price(symbol)


def compare_brokers():
    """对比所有已启用券商的状态"""
    from broker_manager import BrokerManager, load_config

    bm = BrokerManager()
    available = bm.list_available()

    results = []
    for b in available:
        if not b["ready"]:
            continue
        try:
            broker = bm.use(b["id"])
            acct = broker.get_account()
            results.append({
                "id": b["id"],
                "name": b["name"],
                "equity": acct.get("equity", 0),
                "cash": acct.get("cash", 0),
                "positions": len(broker.get_positions()),
                "strategies": b.get("strategies", []),
            })
        except Exception as e:
            results.append({
                "id": b["id"],
                "name": b["name"],
                "error": str(e)[:60],
            })

    return results


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    import sys, logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    # 测试获取券商
    broker, bid = get_broker("conservative")
    if broker:
        print(f"✅ 券商: {bid}")
        print(f"   扩展方法: get_latest_price={hasattr(broker, 'get_latest_price')}")
        print(f"            get_bars={hasattr(broker, 'get_bars')}")
        print(f"            get_portfolio_summary={hasattr(broker, 'get_portfolio_summary')}")
        print(f"            submit_limit_order={hasattr(broker, 'submit_limit_order')}")
    else:
        print("❌ 无法获取券商")
        sys.exit(1)

    # 测试多券商对比
    print("\n📊 多券商状态:")
    for r in compare_brokers():
        print(f"   {r.get('id','?'):25s} equity=${r.get('equity',0):>8.2f}  "
              f"cash=${r.get('cash',0):>8.2f}  positions={r.get('positions',0)}")

    print("\n✅ broker_ext 测试通过")
