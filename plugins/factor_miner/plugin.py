"""
因子矿工插件
===========
每日自动计算所有因子的 IC 排名，写入 factor_ranking.json
给信号系统提供最新因子有效性数据
"""
import logging
import os
import sys

logger = logging.getLogger("quant.plugins.factor_miner")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugin_loader import StrategyPlugin
import signal_bus


class Plugin(StrategyPlugin):
    name = "factor_miner"
    display_name = "因子矿工"
    description = "计算31个因子的IC排名，为选股提供动态权重依据"
    version = "2.0.0"
    schedule = "daily"
    enabled = True

    def generate_signals(self) -> list[dict]:
        from data_prod import load_price_cache, compute_indicators
        from spy_source import get_spy
        from factor_ranking import run_factor_ranking

        logger.info("⛏️ 因子矿工开始挖掘...")

        cache = load_price_cache()
        if not cache:
            logger.warning("缓存为空，跳过")
            return []

        # 确保指标计算
        cache = {t: compute_indicators(df) for t, df in cache.items()}

        # 获取 spy 数据
        spy = get_spy()
        if spy is not None:
            spy = compute_indicators(spy)

        # 运行因子排名（包含 FactorMiner 计算+IC排名+写入 ranking.json）
        result = run_factor_ranking(cache, spy_df=spy)

        if result and result.get("top_factors"):
            top = result["top_factors"][:5]
            logger.info(f"  ✅ 因子矿工完成: {result.get('total_factors', 0)}个因子")
            logger.info(f"  TOP5: {top}")

            # 写入信号总线
            signal_bus.write_signal(
                self.name, [],
                metadata={
                    "total_factors": result.get("total_factors", 0),
                    "top_factors": top,
                    "timestamp": result.get("timestamp", ""),
                },
            )
        else:
            logger.warning("  ⚠️ 因子矿工无结果")

        return []

    def get_info(self) -> dict:
        info = super().get_info()
        info["schedule"] = "daily"
        return info
