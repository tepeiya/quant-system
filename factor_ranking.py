"""
因子排名与信号增强 — 用 FactorMiner 的高级因子提升选股质量
====================================================
功能:
  1. 计算25个因子的IC排名
  2. 选出最近最有效的top因子
  3. 用这些因子增强 daily_signal 的评分

用法:
  python3 factor_ranking.py              # 显示因子排名
  python3 factor_ranking.py --enhance     # 生成增强后的信号
"""

import os, sys, json, logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quant.factor_ranking")

from data_prod import load_price_cache, compute_indicators
from spy_source import get_spy
from factor_miner import FactorMiner

RANKING_FILE = "config/factor_ranking.json"
OUTPUT_DIR = "signals"


def compute_forward_returns(cache: dict, tickers: list,
                            forward_days: int = 20) -> dict:
    """
    计算每只股票的未来N日收益

    参数:
        cache: 价格缓存
        tickers: 股票列表
        forward_days: 未来多少天（默认20交易日≈1个月）

    返回:
        {ticker: future_return_pct}
    """
    returns = {}
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < forward_days + 60:
            continue
        close = df["Close"].values
        today = close[-1]
        if today <= 0:
            continue
        future = close[-1 - forward_days]
        ret = (today / future - 1) * 100
        returns[t] = ret
    return returns


def run_factor_ranking(cache: dict = None, spy_df=None,
                       top_n: int = 10) -> dict:
    """
    运行因子排名，找出最近最有效的因子

    参数:
        cache: 价格缓存（None则自动加载）
        spy_df: SPY数据
        top_n: 返回TopN有效因子

    返回:
        dict: {
            "factors": [{"factor": "momentum_21d", "ic_rank": 0.12, ...}],
            "top_factors": ["momentum_21d", "volume_ratio_1", ...],
            "timestamp": "2026-06-19"
        }
    """
    if cache is None:
        cache = load_price_cache()
        cache = {t: compute_indicators(df) for t, df in cache.items()}

    if spy_df is None:
        spy_df = get_spy()
        if spy_df is not None:
            spy_df = compute_indicators(spy_df)

    tickers = sorted(cache.keys())[:200]

    # 计算未来收益（过去20天的实际收益作为代理）
    forward_returns = compute_forward_returns(cache, tickers)

    # 获取有效tickers
    valid_tickers = [t for t in tickers if t in forward_returns]

    # 计算因子
    miner = FactorMiner(cache)
    factor_df = miner.compute_all(tickers=valid_tickers, spy_df=spy_df)

    if factor_df.empty:
        logger.warning("因子计算无结果")
        return {"factors": [], "top_factors": []}

    # 加入未来收益
    factor_df["future_return"] = factor_df["ticker"].map(forward_returns)
    factor_df = factor_df.dropna(subset=["future_return"])

    # 排名所有因子
    ranking = miner.rank_factors(factor_df, min_samples=15)

    if ranking.empty:
        return {"factors": [], "top_factors": []}

    # 格式化为列表
    factors = []
    for _, r in ranking.iterrows():
        factors.append({
            "factor": r["factor"],
            "ic_rank": round(float(r["ic_rank"]), 4),
            "ic_pearson": round(float(r["ic_pearson"]), 4),
            "samples": int(r["samples"]),
            "abs_ic": round(float(r["abs_ic"]), 4),
        })

    # 取TopN有效因子
    top_factors = [f["factor"] for f in factors[:top_n]
                   if abs(f["ic_rank"]) > 0.03]

    result = {
        "timestamp": str(datetime.now()),
        "total_factors": len(factors),
        "factors": factors,
        "top_factors": top_factors,
        "stock_count": len(factor_df),
    }

    # 保存到文件
    os.makedirs("config", exist_ok=True)
    with open(RANKING_FILE, "w") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info(f"因子排名完成: {len(factors)}个因子, "
                f"{len(top_factors)}个有效, {len(factor_df)}只股票")
    return result


def enhance_signal(cache: dict = None, spy_df=None) -> dict:
    """
    用因子排名增强 daily_signal 的选股评分

    1. 先运行因子排名获取当前有效因子
    2. 用有效因子的权重增强评分
    3. 返回增强后的买入选股列表
    """
    if cache is None:
        cache = load_price_cache()
        cache = {t: compute_indicators(df) for t, df in cache.items()}

    if spy_df is None:
        spy_df = get_spy()
        if spy_df is not None:
            spy_df = compute_indicators(spy_df)

    # 1. 因子排名
    ranking = run_factor_ranking(cache, spy_df)
    top_factors = ranking.get("top_factors", [])

    if not top_factors:
        logger.info("无有效因子，使用默认评分")
        return {}

    logger.info(f"有效因子({len(top_factors)}个): {top_factors[:6]}")

    # 2. 计算每只股票在这些因子上的综合得分
    miner = FactorMiner(cache)
    tickers = sorted(cache.keys())[:200]
    valid_tickers = [t for t in tickers
                     if cache[t] is not None and len(cache[t]) > 60]

    factor_df = miner.compute_all(tickers=valid_tickers, spy_df=spy_df)
    if factor_df.empty:
        return {}

    # 3. 对每个有效因子做标准化(z-score)，然后求和作为增强分
    available_factors = [f for f in top_factors if f in factor_df.columns]

    if not available_factors:
        logger.info("有效因子在数据中不可用")
        return {}

    # 标准化并加权求和
    factor_df["enhance_score"] = 0
    factor_count = 0
    for f in available_factors:
        col = factor_df[f]
        valid = col.dropna()
        if len(valid) < 10:
            continue
        mean = valid.mean()
        std = valid.std()
        if std > 0:
            factor_df["enhance_score"] += (col - mean) / std
            factor_count += 1

    if factor_count > 0:
        factor_df["enhance_score"] = factor_df["enhance_score"] / factor_count

    # 4. 按增强分排序，返回Top
    result = factor_df.sort_values("enhance_score", ascending=False)
    result = result.dropna(subset=["enhance_score"])

    enhanced = []
    for _, r in result.head(20).iterrows():
        enhanced.append({
            "ticker": r["ticker"],
            "price": round(float(r.get("price", 0)), 2),
            "enhance_score": round(float(r.get("enhance_score", 0)), 4),
            "top_factors": available_factors[:5],
        })

    # 保存增强信号
    signal_file = f"{OUTPUT_DIR}/signal_enhanced.json"
    with open(signal_file, "w") as f:
        json.dump({
            "time": str(datetime.now()),
            "top_factors": available_factors,
            "candidates": enhanced,
        }, f, indent=2)

    logger.info(f"增强信号已保存: {len(enhanced)}只候选")
    return {"candidates": enhanced, "top_factors": available_factors}


def print_ranking(result: dict):
    """打印因子排名报告"""
    factors = result.get("factors", [])
    if not factors:
        print("\n❌ 无因子排名数据")
        return

    print("\n" + "=" * 65)
    print("  🧬 因子有效性排名")
    print(f"  {result.get('timestamp', '')[:16]}")
    print("=" * 65)
    print(f"  总因子: {result.get('total_factors', 0)}  有效因子: {len(result.get('top_factors', []))}  "
          f"样本股票: {result.get('stock_count', 0)}")
    print()
    print(f"  {'排名':>4} {'因子名':<28} {'IC秩相关':>10} {'IC皮尔逊':>10} {'样本':>6}")
    print(f"  {'-'*60}")

    for i, f in enumerate(factors[:15], 1):
        print(f"  {i:>4} {f['factor']:<28} {f['ic_rank']:>+10.4f} "
              f"{f['ic_pearson']:>+10.4f} {f['samples']:>6}")

    top = result.get("top_factors", [])
    if top:
        print(f"\n  ✅ 当前有效因子 ({len(top)}个):")
        for f in top[:8]:
            print(f"    · {f}")
    print("=" * 65)


if __name__ == "__main__":
    if "--enhance" in sys.argv:
        r = enhance_signal()
        if r.get("candidates"):
            print(f"\n✅ 增强信号: {len(r['candidates'])}只候选")
            for c in r["candidates"][:10]:
                print(f"  {c['ticker']:6s} 增强分{c['enhance_score']:+.2f}  ${c['price']:.2f}")
    else:
        r = run_factor_ranking()
        print_ranking(r)
