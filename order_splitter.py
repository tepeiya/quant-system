"""
分批建仓/减仓执行器
=================
原理：一次性全仓买入可能买在最高点，分批买卖可以优化入场出场价。

买入策略：
  首次：资金60% → 买入
  如果价格跌2%：剩余40% → 补仓（摊低成本）

卖出策略：
  首次：持仓50% → 卖出
  如果价格涨3%：剩余50% → 卖出（卖在更高点）

用法：
  from order_splitter import OrderSplitter
  splitter = OrderSplitter()
  orders = splitter.split_buy("AAPL", 10, $150)
  # → [{"qty": 6, "delay": 0}, {"qty": 4, "delay": "wait_drop_2%"}]
"""

import logging
import time
import os
import requests
from datetime import datetime

logger = logging.getLogger("quant.split")

from system_config import get as get_cfg


class OrderSplitter:
    """订单分割器"""

    def __init__(self):
        self.buy_first_pct = get_cfg("split_buy_first", 0.6)
        self.buy_drop_pct = get_cfg("split_buy_drop", 2.0)
        self.sell_first_pct = get_cfg("split_sell_first", 0.5)
        self.sell_rise_pct = get_cfg("split_sell_rise", 3.0)
        self.min_wait_seconds = get_cfg("split_min_wait", 120)

    def split_buy(self, symbol: str, total_qty: int, price: float) -> list:
        """生成分批买入订单"""
        if total_qty < 2:
            return [{"symbol": symbol, "qty": total_qty, "type": "market", "delay": 0}]

        first_qty = max(1, int(total_qty * self.buy_first_pct))
        second_qty = total_qty - first_qty

        return [
            {"symbol": symbol, "qty": first_qty, "type": "market", "delay": 0},
            {"symbol": symbol, "qty": second_qty,
             "type": "limit_after_drop",
             "drop_pct": self.buy_drop_pct,
             "reference_price": price,
             "delay": self.min_wait_seconds},
        ]

    def split_sell(self, symbol: str, total_qty: int, price: float) -> list:
        """生成分批卖出订单"""
        if total_qty < 2:
            return [{"symbol": symbol, "qty": total_qty, "type": "market", "delay": 0}]

        first_qty = max(1, int(total_qty * self.sell_first_pct))
        second_qty = total_qty - first_qty

        return [
            {"symbol": symbol, "qty": first_qty, "type": "market", "delay": 0},
            {"symbol": symbol, "qty": second_qty,
             "type": "limit_after_rise",
             "rise_pct": self.sell_rise_pct,
             "reference_price": price,
             "delay": self.min_wait_seconds},
        ]

    def execute_split_orders(self, orders: list, client, side: str):
        """执行分批订单链"""
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        results = []
        for order in orders:
            sym = order["symbol"]
            qty = order["qty"]

            if order["type"] == "market":
                resp = client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=qty,
                    side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                ))
                results.append(resp)
                logger.info(f"  分批{side} {sym} x{qty} 市价")

            elif order["type"] == "limit_after_drop":
                # 等待价格下跌后限价买入
                limit_price = round(order["reference_price"] * (1 - order["drop_pct"] / 100), 2)
                logger.info(f"  挂单: {sym} x{qty} @ ${limit_price} (跌{order['drop_pct']}%)")
                try:
                    resp = client.submit_order(LimitOrderRequest(
                        symbol=sym, qty=qty, side=OrderSide.BUY,
                        limit_price=limit_price,
                        time_in_force=TimeInForce.DAY,
                    ))
                    results.append(resp)
                except Exception as e:
                    logger.warning(f"  挂单失败: {e}")

            elif order["type"] == "limit_after_rise":
                limit_price = round(order["reference_price"] * (1 + order["rise_pct"] / 100), 2)
                logger.info(f"  挂单: {sym} x{qty} @ ${limit_price} (涨{order['rise_pct']}%)")
                try:
                    resp = client.submit_order(LimitOrderRequest(
                        symbol=sym, qty=qty, side=OrderSide.SELL,
                        limit_price=limit_price,
                        time_in_force=TimeInForce.DAY,
                    ))
                    results.append(resp)
                except Exception as e:
                    logger.warning(f"  挂单失败: {e}")

            if order.get("delay", 0) > 0:
                time.sleep(min(order["delay"], 5))  # 最多等5秒

        return results


if __name__ == "__main__":
    splitter = OrderSplitter()
    print("10股买入:")
    for o in splitter.split_buy("AAPL", 10, 150):
        print(f"  {o}")
    print("\n10股卖出:")
    for o in splitter.split_sell("AAPL", 10, 150):
        print(f"  {o}")
