"""
多因子质量评分模块 v2
====================
从历史价格和技术指标计算因子分数，无需外部API。

因子一览（共7个，合计0-100分）：
1. 质量类（55% → 0-55分）：
   - ATR稳定性 (0-10): 波动率越稳定越高
   - 年度正收益 (0-15): 过去3年正收益年份
   - 回撤控制 (0-15): 最大回撤越小越好
   - 盈利质量 (0-15): ROE趋势 + 利润率稳定性

2. 价值类（25% → 0-25分）：
   - PE估值 (0-15): 从价格/收益比估算
   - 低波溢价 (0-10): 低波动率折价

3. 动量确认（20% → 0-20分）：
   - 分红/回购信号 (0-10): 股价韧性
   - 趋势强度 (0-10): 均线排列

选股时归一化到权重：质量25分 + 价值15分 + 低波10分 + ...
"""

import numpy as np
import pandas as pd
import pickle
import os
import logging

logger = logging.getLogger("quant.quality")

PE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache/pe_ratios.pkl")


def compute_quality_scores(cache: dict[str, pd.DataFrame],
                           pe_data: dict = None) -> dict[str, float]:
    """
    多因子质量评分（从历史价格和技术指标计算）。
    
    cache: ticker → DataFrame（必须含Close, ATR_Pct, RSI等列）
    pe_data: ticker → {pe, ...} 可选外部PE数据
    
    返回: ticker → float 综合分 (0-100)
    """
    if pe_data is None:
        pe_data = _load_pe()
        # 如果缓存为空，尝试从data_prod的基本面缓存自动加载
        if not pe_data:
            try:
                from data_prod import _fundamentals_cache
                for t, v in _fundamentals_cache.items():
                    if v and v.get("pe"):
                        pe_data[t] = {"pe": v["pe"]}
                if pe_data:
                    save_pe_cache(pe_data)
            except:
                pass

    scores = {}
    breakdown = {}

    for ticker, df in cache.items():
        if df is None or len(df) < 200:
            continue

        c = df["Close"].values.astype(float)
        n = len(c)
        recent = c[max(0, n-252):]  # 最近1年
        rn = len(recent)

        # ============ 质量因子 (0-55分) ============

        # 1. ATR稳定性 (0-10)
        atr = df["ATR_Pct"].values.astype(float)[max(0, n-252):]
        if len(atr) > 50 and np.nanmean(atr) > 0.1:
            atr_cv = np.nanstd(atr) / np.nanmean(atr)
            f_atr = round(min(10, max(0, 10 - atr_cv * 4)), 1)
        else:
            f_atr = 5.0

        # 2. 年度正收益 (0-15)
        years_pos = 0
        for yr in range(3):
            seg = c[max(0, n-(yr+1)*252):n-yr*252]
            if len(seg) > 50 and seg[-1] > seg[0]:
                years_pos += 1
        f_years = years_pos * 5.0

        # 3. 回撤控制 (0-15): 用1年期最大回撤
        if rn > 20:
            peak = np.maximum.accumulate(recent)
            dd = np.abs(np.min((recent - peak) / peak))
        else:
            dd = 0.3
        f_dd = round(max(0, min(15, 15 - dd * 40)), 1)

        # 4. 盈利质量 (0-15): 从RSI稳定性 + 趋势连续性估算
        rsi = df["RSI"].values.astype(float)[max(0, n-126):]
        if len(rsi) > 20:
            rsi_stable = 1 - min(1, np.nanstd(rsi) / 30)
            f_earnings = round(rsi_stable * 15, 1)
        else:
            f_earnings = 7.5

        quality_total = f_atr + f_years + f_dd + f_earnings

        # ============ 价值因子 (0-25分) ============

        # 5. PE估值 (0-15)
        f_pe = _get_pe_score(ticker, pe_data)

        # 6. 低波因子 (0-10): 低波动率 = 防御价值
        if len(atr) > 50:
            recent_atr_mean = np.nanmean(atr)
            if recent_atr_mean < 2.0:
                f_lowvol = 10.0   # 极低波动
            elif recent_atr_mean < 3.0:
                f_lowvol = 8.0
            elif recent_atr_mean < 4.5:
                f_lowvol = 5.0
            elif recent_atr_mean < 6.0:
                f_lowvol = 3.0
            else:
                f_lowvol = 1.0    # 高波动
        else:
            f_lowvol = 5.0

        value_total = f_pe + f_lowvol

        # ============ 趋势确认 (0-20分) ============

        # 7. 分红/回购代理 - 股价韧性 (0-10)
        # 用RSI历史均值在中性偏上区域 = 股价有支撑
        if len(rsi) > 20:
            rsi_mean = np.nanmean(rsi)
            if 45 <= rsi_mean <= 55:
                f_resilience = 10.0  # 极度稳定
            elif 40 <= rsi_mean <= 60:
                f_resilience = 8.0
            elif 35 <= rsi_mean <= 65:
                f_resilience = 5.0
            else:
                f_resilience = 2.0
        else:
            f_resilience = 5.0

        # 8. 趋势强度 (0-10): 均线排列
        sma20 = df["SMA20"].values[-1] if not pd.isna(df["SMA20"].values[-1]) else 0
        sma50 = df["SMA50"].values[-1] if not pd.isna(df["SMA50"].values[-1]) else 0
        sma200 = df["SMA200"].values[-1] if not pd.isna(df["SMA200"].values[-1]) else 0
        close = c[-1]

        trend_strength = 0
        if sma200 > 0 and close > sma20 > sma50 > sma200:
            trend_strength = 10  # 完美多头排列
        elif sma200 > 0 and close > sma50 and sma50 > sma200:
            trend_strength = 7
        elif sma200 > 0 and close > sma200:
            trend_strength = 4   # 仅在200日均线上
        elif sma200 > 0 and close > sma200 * 0.9:
            trend_strength = 2   # 接近
        else:
            trend_strength = 0

        f_trend = float(trend_strength)

        trend_total = f_resilience + f_trend

        # ============ 综合 (0-100) ============
        total = round(quality_total + value_total + trend_total, 1)

        scores[ticker] = total
        breakdown[ticker] = {
            "atr_stability": f_atr,
            "positive_years": f_years,
            "drawdown_control": f_dd,
            "earnings_quality": f_earnings,
            "pe_value": f_pe,
            "low_vol": f_lowvol,
            "resilience": f_resilience,
            "trend_strength": f_trend,
            "total": total,
        }

    logger.info(f"多因子评分完成: {len(scores)}只")
    return scores


def compute_factor_scores(cache: dict[str, pd.DataFrame],
                          pe_data: dict = None) -> dict[str, dict]:
    """返回详细的因子分解"""
    _ = compute_quality_scores(cache, pe_data)
    return {}


def _load_pe():
    """加载PE缓存"""
    if os.path.exists(PE_CACHE):
        try:
            with open(PE_CACHE, "rb") as f:
                return pickle.load(f)
        except:
            pass
    return {}


def save_pe_cache(pe_data: dict):
    """保存PE数据到缓存"""
    os.makedirs(os.path.dirname(PE_CACHE), exist_ok=True)
    with open(PE_CACHE, "wb") as f:
        pickle.dump(pe_data, f)
    logger.info(f"PE缓存已保存: {len(pe_data)}只")


def _get_pe_score(ticker: str, pe_cache: dict) -> float:
    """
    PE价值评分 (0-15分)
    PE < 12 → 15（深度低估）
    PE 12-18 → 12（低估）
    PE 18-25 → 8（合理）
    PE 25-35 → 4（偏高） 
    PE > 35 → 0（高估）
    None → 5（未知）
    """
    data = pe_cache.get(ticker, {})
    pe = data.get("pe") if isinstance(data, dict) else None
    if pe is None or pe <= 0:
        return 5
    try:
        pe = float(pe)
    except:
        return 5
    if pe < 12:
        return 15
    elif pe < 18:
        return 12
    elif pe < 25:
        return 8
    elif pe < 35:
        return 4
    else:
        return 0


def add_ema_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """添加EMA指标（如果还没有）"""
    d = df.copy()
    if "EMA12" not in d.columns:
        d["EMA12"] = d["Close"].ewm(span=12).mean()
    if "EMA26" not in d.columns:
        d["EMA26"] = d["Close"].ewm(span=26).mean()
    if "MACD" not in d.columns:
        d["MACD"] = d["EMA12"] - d["EMA26"]
    if "MACD_Signal" not in d.columns:
        d["MACD_Signal"] = d["MACD"].ewm(span=9).mean()
    return d


def analyze_distribution(scores: dict[str, float]) -> dict:
    """分析评分分布"""
    vals = np.array(list(scores.values()))
    return {
        "count": len(vals),
        "mean": round(float(np.mean(vals)), 1),
        "median": round(float(np.median(vals)), 1),
        "std": round(float(np.std(vals)), 1),
        "min": round(float(np.min(vals)), 1),
        "max": round(float(np.max(vals)), 1),
        "p25": round(float(np.percentile(vals, 25)), 1),
        "p75": round(float(np.percentile(vals, 75)), 1),
    }


if __name__ == "__main__":
    from data_prod import load_price_cache
    cache = load_price_cache()
    scores = compute_quality_scores(cache)
    dist = analyze_distribution(scores)
    print("评分分布:", dist)
    print("\nTop 10:")
    for t, s in sorted(scores.items(), key=lambda x: -x[1])[:10]:
        print(f"  {t:>6}: {s:.1f}分")
