"""
换手率衰减模块
=============
原理：信号推荐买入的股票，如果当前持仓中有相同股票且浮盈为正，则保留不卖。
减少不必要的交易次数，降低滑点成本。

策略：
  每次调仓时，先检查当前持仓：
  - 浮盈 > 0 且评分 > 40 → 保留（不卖）
  - 浮盈 < -5% → 强制卖出（止损优先）
  - 其他 → 按信号评分决定是否换股

用法：
  from churn_reducer import ChurnReducer
  reducer = ChurnReducer()
  orders = reducer.filter_orders(signal, current_positions)
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("quant.churn")

from system_config import get as get_cfg


class ChurnReducer:
    """换手率衰减器：减少不必要的交易"""

    def __init__(self):
        self.min_hold_days = get_cfg("min_hold_days", 5)
        self.keep_threshold = get_cfg("churn_keep_score", 40)

    def filter_buys(self, candidates: list, current_positions: dict,
                    score_threshold: float = 50) -> list:
        """
        过滤买入候选：
        1. 已持仓且浮盈为正 → 跳过（已有仓位）
        2. 已持仓但浮盈<0 → 如果信号评分高可以加仓
        3. 新买入候选 → 按评分排序
        """
        filtered = []
        held_symbols = set(current_positions.keys())

        for c in candidates:
            symbol = c["ticker"]

            if symbol in held_symbols:
                pos = current_positions[symbol]
                pnl = pos.get("pnl_pct", 0)

                if pnl > 3:
                    # 浮盈超过3%，保留不操作
                    continue
                elif pnl < -10:
                    # 亏损超过10%，如果评分不够高则不加仓
                    if c.get("score", 0) < score_threshold + 10:
                        continue

            filtered.append(c)

        return filtered

    def filter_sells(self, held_symbols: list,
                     current_positions: dict,
                     new_top_symbols: list,
                     score_threshold: float = 50) -> list:
        """
        过滤卖出：
        1. 浮盈 > 5% 且评分不太差 → 保留（让赢家跑）
        2. 浮盈 < -10% → 强制卖出（止损）
        3. 不在新信号TopN中 → 卖出
        """
        to_sell = []
        keep = []

        for sym in held_symbols:
            pos = current_positions.get(sym, {})
            pnl = pos.get("pnl_pct", 0)

            # 强制止损
            if pnl < -15:
                to_sell.append(sym)
                continue

            # 大浮盈保留
            if pnl > 8 and sym in new_top_symbols:
                keep.append(sym)
                continue

            # 不在新信号中 → 卖出
            if sym not in new_top_symbols:
                to_sell.append(sym)
                continue

            keep.append(sym)

        return to_sell, keep


if __name__ == "__main__":
    # 测试
    reducer = ChurnReducer()
    test_positions = {
        "AAPL": {"pnl_pct": 5.2},
        "MSFT": {"pnl_pct": -2.1},
        "NVDA": {"pnl_pct": -18.3},
    }
    test_candidates = [
        {"ticker": "AAPL", "score": 65},
        {"ticker": "GOOGL", "score": 72},
        {"ticker": "EBAY", "score": 80},
    ]

    buys = reducer.filter_buys(test_candidates, test_positions)
    print(f"买入候选: {[c['ticker'] for c in buys]}")

    sells, keeps = reducer.filter_sells(
        list(test_positions.keys()), test_positions,
        ["AAPL", "GOOGL", "EBAY"]
    )
    print(f"卖出: {sells}")
    print(f"保留: {keeps}")
