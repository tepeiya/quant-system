"""
因子进化插件
===========
每日自动根据IC调整因子权重
"""
import logging
import os
import sys

logger = logging.getLogger("quant.plugins.factor_evolve")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugin_loader import StrategyPlugin
import signal_bus


class Plugin(StrategyPlugin):
    name = "factor_evolve"
    display_name = "因子进化"
    description = "根据IC值自动调整因子权重（动量/质量/趋势/价值/低波/成交量）"
    version = "2.0.0"
    schedule = "daily"
    enabled = True

    def generate_signals(self) -> list[dict]:
        """执行因子学习并应用新权重"""
        from factor_learner import run_learning

        logger.info("🧬 因子进化开始...")
        result = run_learning(apply=True)

        if result:
            # 保存结果到信号总线
            signal_bus.write_signal(
                self.name, [],
                metadata={
                    "action": "factor_evolve",
                    "status": "completed",
                    "weights_applied": True,
                },
            )
            logger.info(f"  ✅ 因子进化完成，新权重已应用")
        else:
            logger.warning("  ⚠️ 因子进化无结果")

        return []

    def get_info(self) -> dict:
        info = super().get_info()
        info["schedule"] = "daily"
        return info
