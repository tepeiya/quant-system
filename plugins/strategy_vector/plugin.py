"""
保守策略插件 (VectorStrategy)
=============================
包装 daily_signal.py 为标准插件接口
"""
import logging
import os
import sys

logger = logging.getLogger("quant.plugins.vector")

# 确保能找到项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugin_loader import StrategyPlugin
import signal_bus


class Plugin(StrategyPlugin):
    name = "conservative"
    display_name = "保守策略"
    description = "多因子综合评分（动量+质量+趋势+低波+成交量）"
    version = "2.0.0"
    schedule = "daily"
    enabled = True

    def generate_signals(self) -> list[dict]:
        """调用 daily_signal.generate_signals() 并写入总线"""
        from daily_signal import generate_signals
        result = generate_signals()
        if not result:
            return []

        candidates = result.get("top_scores", [])
        buy_list = [s["ticker"] for s in result.get("buy_candidates", [])]
        market = result.get("market", {})

        # 写入信号总线
        signal_bus.write_signal(
            self.name, candidates,
            market=market,
            buy_list=buy_list,
            metadata={"source": "daily_signal"},
        )

        logger.info(f"  ✅ 保守策略: {len(candidates)}只候选, {len(buy_list)}只买入")
        return candidates

    def get_info(self) -> dict:
        info = super().get_info()
        info["signal_file"] = "signals/signal_{date}.json"
        return info
