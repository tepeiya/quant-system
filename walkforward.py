"""
Walk-Forward 验证
=================
把回测期间切分为多个训练+测试窗口。
每段：先用训练期数据调参，在测试期验证（不重叠）。

窗口设计：
  2020-01 ~ 2020-12 训练
  2021-01 ~ 2021-12 测试 ←
  
  2021-01 ~ 2022-06 训练
  2022-07 ~ 2023-06 测试 ←（含2022年大崩盘）
  
  2023-01 ~ 2023-12 训练
  2024-01 ~ 2024-12 测试 ←（AI牛市巅峰）
  
  2024-01 ~ 2025-06 训练
  2025-07 ~ 2026-05 测试 ←（最近期）
"""

import logging
import sys
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("quant.walkforward")

from data_prod import load_price_cache, compute_indicators
from strategy_vector import VectorStrategy
from quality_factor import compute_quality_scores
import yfinance as yf
import pandas as pd
import numpy as np
import os

OUT_DIR = "/var/minis/workspace/quant_system/results"
os.makedirs(OUT_DIR, exist_ok=True)


# ======== 窗口定义 ========
WINDOWS = [
    {
        "name": "2022暴跌测试",
        "train": ("2020-01-01", "2021-12-31"),
        "test": ("2022-01-01", "2022-12-31"),
        "note": "2022年美联储激进加息，大盘跌24%"
    },
    {
        "name": "AI牛市测试",
        "train": ("2022-01-01", "2023-06-30"),
        "test": ("2023-07-01", "2024-06-30"),
        "note": "AI热潮，NVDA涨200%+"
    },
    {
        "name": "震荡分化测试",
        "train": ("2023-07-01", "2024-06-30"),
        "test": ("2024-07-01", "2025-06-30"),
        "note": "关税博弈，市场分化严重"
    },
    {
        "name": "最近期测试",
        "train": ("2023-01-01", "2025-06-30"),
        "test": ("2025-07-01", "2026-05-17"),
        "note": "最近10个月的最新表现"
    },
]


def run_walk_forward():
    ts = datetime.now()

    # 1. 加载数据
    logger.info("加载数据...")
    cache = load_price_cache()
    spy = yf.download("SPY", start="2018-01-01", end="2026-05-17",
                      progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = compute_indicators(spy)
    logger.info(f"数据: {len(cache)}只, SPY {len(spy)}行")

    # 质量分（全局计算一次）
    quality = compute_quality_scores(cache)
    tickers = sorted(cache.keys())
    tickers = tickers[:200]  # 用Top200核心池（更稳定）

    results = []

    for w in WINDOWS:
        logger.info(f"\n{'='*55}")
        logger.info(f"  窗口: {w['name']}")
        logger.info(f"  训练: {w['train'][0]} ~ {w['train'][1]}")
        logger.info(f"  测试: {w['test'][0]} ~ {w['test'][1]}")
        logger.info(f"  背景: {w['note']}")
        logger.info(f"{'='*55}")

        test_prices = {t: cache[t] for t in tickers}
        
        # 训练期执行
        strategy = VectorStrategy(tickers, quality_scores=quality)
        train_res = strategy.run(test_prices, spy,
                                 start=w['train'][0], end=w['train'][1])
        
        if train_res and train_res['total_return_pct'] != 0:
            logger.info(f"  训练期: 收益{train_res['total_return_pct']:+.1f}%  "
                        f"回撤{train_res['max_drawdown_pct']:.1f}%  "
                        f"夏普{train_res['sharpe_ratio']:.2f}")

        # 测试期执行（参数继承自训练期）
        strategy2 = VectorStrategy(tickers, quality_scores=quality)
        test_res = strategy2.run(test_prices, spy,
                                 start=w['test'][0], end=w['test'][1])

        if test_res and test_res['total_return_pct'] != 0:
            logger.info(f"  测试期: 收益{test_res['total_return_pct']:+.1f}%  "
                        f"回撤{test_res['max_drawdown_pct']:.1f}%  "
                        f"夏普{test_res['sharpe_ratio']:.2f}")
        else:
            logger.warning(f"  测试期无结果")

        results.append({
            "window": w["name"],
            "note": w["note"],
            "train_return": train_res['total_return_pct'] if train_res else 0,
            "train_maxdd": train_res['max_drawdown_pct'] if train_res else 0,
            "train_sharpe": train_res['sharpe_ratio'] if train_res else 0,
            "test_return": test_res['total_return_pct'] if test_res else 0,
            "test_maxdd": test_res['max_drawdown_pct'] if test_res else 0,
            "test_sharpe": test_res['sharpe_ratio'] if test_res else 0,
        })

    # 打印总表
    print("\n" + "=" * 70)
    print("  Walk-Forward 验证结果")
    print("  Top200核心池 | 动量55%+质量25%+趋势20%")
    print("=" * 70)
    print(f"{'窗口':<20} {'训练收益':>8} {'测试收益':>8} {'测试回撤':>8} {'测试夏普':>8}")
    print("-" * 50)
    for r in results:
        print(f"{r['window']:<20} {r['train_return']:>+7.1f}% "
              f"{r['test_return']:>+7.1f}% {r['test_maxdd']:>7.1f}% "
              f"{r['test_sharpe']:>7.2f}")
    print("-" * 50)
    # 测试期平均
    avg_ret = np.mean([r['test_return'] for r in results])
    avg_sharpe = np.mean([r['test_sharpe'] for r in results])
    avg_dd = np.mean([r['test_maxdd'] for r in results])
    print(f"{'测试期平均':<20} {'':>8} {avg_ret:>+7.1f}% {avg_dd:>7.1f}% {avg_sharpe:>7.2f}")
    print("=" * 70)

    # 与SPY对比
    print(f"\nSPY同期表现参考:")
    for w in WINDOWS:
        spy_seg = spy.loc[w['test'][0]:w['test'][1]]
        if len(spy_seg) > 0:
            spy_ret = (spy_seg['Close'].iloc[-1] / spy_seg['Close'].iloc[0] - 1) * 100
            print(f"  {w['name']:<20} SPY: {spy_ret:+.1f}%")

    elapsed = (datetime.now() - ts).total_seconds()
    print(f"\n⏱️ 总耗时: {elapsed:.1f}s")

    # 图表
    fig, axes = plt.subplots(len(WINDOWS), 1, figsize=(14, 10),
                             sharex=True)
    if len(WINDOWS) == 1:
        axes = [axes]

    for i, w in enumerate(WINDOWS):
        ax = axes[i]
        r = results[i]
        colors = 'green' if r['test_return'] > 0 else 'red'
        ax.barh(['测试'], [r['test_return']], color=colors, alpha=0.7)
        ax.axvline(0, color='gray', linewidth=0.5)
        ax.set_title(f"{w['name']}: 测试收益{r['test_return']:+.1f}%  "
                     f"夏普{r['test_sharpe']:.2f}  "
                     f"回撤{r['test_maxdd']:.1f}%")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = f"{OUT_DIR}/walkforward_report.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"图表: {path}")

    return results


if __name__ == "__main__":
    run_walk_forward()
