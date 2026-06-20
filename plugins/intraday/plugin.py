"""
日内交易策略插件
==============
包装 intraday.py 为标准插件接口
"""
import logging
import os
import sys

logger = logging.getLogger("quant.plugins.intraday")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugin_loader import StrategyPlugin
import signal_bus


class Plugin(StrategyPlugin):
    name = "intraday"
    display_name = "日内交易策略"
    description = "盘中实时动量选股+止盈止损+移动止损"
    version = "2.0.0"
    schedule = "intraday"
    enabled = True

    def generate_signals(self) -> list[dict]:
        from intraday import generate_signal
        signal = generate_signal()
        if not signal:
            return []

        candidates = signal.get("candidates", [])
        buy_list = [s.get("ticker") for s in candidates]

        # 写入信号总线
        signal_bus.write_signal(
            self.name, candidates,
            buy_list=buy_list,
            metadata={"scanned": signal.get("all_scanned", 0)},
        )

        logger.info(f"  ✅ 日内策略: {len(candidates)}只候选")
        return candidates

    def get_info(self) -> dict:
        info = super().get_info()
        info["signal_file"] = "signals/intraday_signal.json"
        info["scan_interval"] = "15分钟"
        return info
