"""
激进动量策略插件
==============
包装 strategy_momentum.py 为标准插件接口
"""
import logging
import os
import sys

logger = logging.getLogger("quant.plugins.momentum")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugin_loader import StrategyPlugin
import signal_bus


class Plugin(StrategyPlugin):
    name = "momentum"
    display_name = "激进动量策略"
    description = "纯动量排名策略（12/6/3月动量加权）"
    version = "2.0.0"
    schedule = "daily"
    enabled = True

    def generate_signals(self) -> list[dict]:
        from data_prod import load_price_cache, compute_indicators
        from strategy_momentum import generate_signals

        cache = load_price_cache()
        if not cache:
            logger.warning("缓存为空")
            return []

        # 确保指标已计算
        for tkr in list(cache.keys()):
            df = cache[tkr]
            if df is not None and "Momentum_12M" not in df.columns:
                cache[tkr] = compute_indicators(df)

        top_tickers = generate_signals(cache, top_n=15)
        if not top_tickers:
            return []

        candidates = [
            {"ticker": t, "score": round(1 - i / len(top_tickers), 3)}
            for i, t in enumerate(top_tickers[:10])
        ]

        # 写入信号总线
        signal_bus.write_signal(
            self.name, candidates,
            buy_list=top_tickers,
            metadata={"source": "strategy_momentum", "count": len(top_tickers)},
        )

        logger.info(f"  ✅ 动量策略: {len(top_tickers)}只")
        return candidates

    def get_info(self) -> dict:
        info = super().get_info()
        info["signal_file"] = "signals/signal_momentum.json"
        return info
