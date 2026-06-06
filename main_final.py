"""
Multi-Factor Momentum+ 最终版
=============================
策略：动量55% + 质量25% + 趋势20%
数据：全S&P 500（502只，缓存优先）
回测：NumPy向量化

运行方式：python3 main_final.py
"""

import logging
import sys
import os
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    stream=sys.stdout)

from data_prod import load_price_cache, compute_indicators
from strategy_vector import VectorStrategy
from quality_factor import compute_quality_scores
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger("quant.final")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    ts = datetime.now()

    # 1. 数据
    logger.info("加载缓存数据...")
    cache = load_price_cache()
    logger.info(f"缓存: {len(cache)}只")

    logger.info("获取SPY...")
    try:
        spy_t = yf.Ticker("SPY")
        spy = spy_t.history(start="2018-01-01", end="2026-05-17", auto_adjust=True)
    except Exception:
        logger.warning("SPY下载失败，将跳过回测")

    if spy is None or len(spy) < 200:
        logger.error("没有有效的SPY数据，无法进行回测")
        return

    spy = compute_indicators(spy)
    logger.info(f"SPY: {len(spy)}行")

    tickers = sorted(cache.keys())
    if len(tickers) < 10:
        logger.error("缓存数据不足，需要至少10只股票")
        return
    logger.info(f"使用缓存中的 {len(tickers)} 只股票")

    # 2. 质量分
    logger.info("计算质量因子...")
    quality = compute_quality_scores(cache)

    # 3. 回测：全S&P 500
    logger.info("\n=== 全S&P 500回测 ===")
    strategy = VectorStrategy(tickers, quality_scores=quality)
    test_prices = {t: cache[t] for t in tickers}
    all_500 = strategy.run(test_prices, spy)

    # 4. 回测：Top200核心池
    logger.info("\n=== Top200核心池回测 ===")
    top200 = tickers[:200]
    tq = {t: quality[t] for t in top200}
    strategy_top = VectorStrategy(top200, quality_scores=tq)
    top_prices = {t: cache[t] for t in top200}
    top200_res = strategy_top.run(top_prices, spy)

    # 5. 打印对比
    elapsed = (datetime.now() - ts).total_seconds()
    print("\n" + "=" * 60)
    print("  Multi-Factor Momentum+ - 最终回测结果")
    print("  动量55% + 质量25% + 趋势20% + ATR波动率仓位")
    print("=" * 60)
    print(f"{'指标':<15} {'全S&P 500':>15} {'Top200核心':>15}")
    print("-" * 45)
    if all_500:
        print(f"{'总收益%':<15} {all_500['total_return_pct']:>13.1f}% {top200_res['total_return_pct']:>13.1f}%")
        print(f"{'年化%':<15} {all_500['annual_return_pct']:>13.1f}% {top200_res['annual_return_pct']:>13.1f}%")
        print(f"{'最大回撤%':<15} {all_500['max_drawdown_pct']:>13.1f}% {top200_res['max_drawdown_pct']:>13.1f}%")
        print(f"{'夏普':<15} {all_500['sharpe_ratio']:>13.2f} {top200_res['sharpe_ratio']:>13.2f}")
    print("=" * 60)
    print(f"耗时: {elapsed:.1f}s")

    # 6. 图表
    if all_500 and top200_res:
        fig, axes = plt.subplots(2, 1, figsize=(14, 8),
                                 gridspec_kw={"height_ratios": [3, 1]})
        eq_all = all_500["equity_curve"]
        eq_top = top200_res["equity_curve"]
        dd_all = all_500["drawdown_curve"]
        dd_top = top200_res["drawdown_curve"]

        ax1 = axes[0]
        ax1.plot(eq_all.index, eq_all.values, color="blue", linewidth=2,
                 label=f"全S&P 500 (夏普{all_500['sharpe_ratio']:.2f})")
        ax1.plot(eq_top.index, eq_top.values, color="orange", linewidth=2,
                 label=f"Top200核心 (夏普{top200_res['sharpe_ratio']:.2f})")
        ax1.set_title("Multi-Factor Momentum+ (2020-01 ~ 2026-05)", fontsize=14)
        ax1.set_ylabel("Portfolio Value ($)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2 = axes[1]
        ax2.fill_between(dd_all.index, 0, dd_all.values, color="blue", alpha=0.2, label="全S&P 500")
        ax2.fill_between(dd_top.index, 0, dd_top.values, color="orange", alpha=0.2, label="Top200")
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        path = os.path.join(OUT_DIR, "final_report.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"图表: {path}")

        # 保存详细数据
        eq_all.to_csv(os.path.join(OUT_DIR, "equity_all500.csv"))
        eq_top.to_csv(os.path.join(OUT_DIR, "equity_top200.csv"))
        logger.info("详细数据已保存")


if __name__ == "__main__":
    main()
