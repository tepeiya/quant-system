"""
配对交易（Pairs Trading）模块
==========================
统计套利策略：找高度相关的一对股票，当价差偏离均值时反向操作。

核心逻辑：
1. 配对选择：计算 S&P 500 股票间的相关系数，找相关系数>0.8的配对
2. 价差计算：对数价差 = ln(P_A) - ln(P_B)，标准化为 z-score
3. 信号生成：z-score > 1.5 卖出A买入B / z-score < -1.5 买入A卖出B
4. 退出条件：z-score 回归到0附近，或者达到止损

用法：
  python3 pairs_trading.py --scan         # 扫描可用配对
  python3 pairs_trading.py --signal       # 生成今日信号
  python3 pairs_trading.py --dashboard    # 输出Web页面
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime

logger = logging.getLogger("quant.pairs")

SIGNALS_DIR = "signals"
CACHE_DIR = "data_cache"
PAIRS_CONFIG = "config/pairs_config.json"
PAIRS_CACHE = "data_cache/pairs_scan.json"


# ===== 配置 =====

DEFAULT_CONFIG = {
    "enabled": True,
    "correlation_threshold": 0.80,    # 最低相关系数
    "spread_window": 60,              # 价差计算窗口（天）
    "zscore_entry": 1.5,              # 入场z-score阈值
    "zscore_exit": 0.3,               # 出场z-score阈值
    "zscore_stop": 3.0,              # 止损z-score阈值
    "max_pairs": 5,                   # 最多同时持几对配对
    "max_hold_days": 30,             # 最大持仓天数
    "atr_stop_pct": 3.0,             # ATR止损比例
}


def load_config() -> dict:
    if os.path.exists(PAIRS_CONFIG):
        with open(PAIRS_CONFIG) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    os.makedirs("config", exist_ok=True)
    with open(PAIRS_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


# ===== 配对选择 =====

def scan_pairs(cache: dict, lookback_days: int = 252) -> list:
    """
    扫描S&P 500，找相关系数>阈值的配对。
    返回：配对列表，按相关系数降序排列。
    """
    cfg = load_config()
    corr_threshold = cfg.get("correlation_threshold", 0.80)

    tickers = sorted(cache.keys())
    if len(tickers) < 10:
        return []

    # 提取收盘价矩阵
    price_matrix = {}
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < lookback_days:
            continue
        price_matrix[t] = df["Close"].tail(lookback_days)

    if len(price_matrix) < 5:
        return []

    # 对齐日期
    common_index = None
    for t, series in price_matrix.items():
        if common_index is None:
            common_index = series.index
        else:
            common_index = common_index.intersection(series.index)

    if common_index is None or len(common_index) < 100:
        return []

    # 构建对齐的价格矩阵
    aligned = {}
    for t, series in price_matrix.items():
        aligned[t] = series.reindex(common_index).dropna()
        if len(aligned[t]) < lookback_days:
            aligned.pop(t)

    if len(aligned) < 5:
        return []

    # 计算对数收益率矩阵
    log_returns = {}
    for t, series in aligned.items():
        log_returns[t] = np.log(series.values / np.roll(series.values, 1))[1:]

    # 计算相关系数矩阵
    tickers_clean = list(log_returns.keys())
    n = len(tickers_clean)
    if n < 2:
        return []

    corr_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n):
            x = log_returns[tickers_clean[i]]
            y = log_returns[tickers_clean[j]]
            min_len = min(len(x), len(y))
            if min_len > 50:
                corr = np.corrcoef(x[:min_len], y[:min_len])[0, 1]
                corr_matrix[i, j] = corr
                corr_matrix[j, i] = corr

    # 找配对
    pairs = []
    for i in range(n):
        for j in range(i+1, n):
            corr = corr_matrix[i, j]
            if corr >= corr_threshold:
                pairs.append({
                    "pair": f"{tickers_clean[i]}/{tickers_clean[j]}",
                    "tickers": [tickers_clean[i], tickers_clean[j]],
                    "correlation": round(float(corr), 4),
                    "lookback": lookback_days,
                })

    # 按相关系数降序
    pairs.sort(key=lambda x: -x["correlation"])

    # 保存缓存
    os.makedirs("data_cache", exist_ok=True)
    with open(PAIRS_CACHE, "w") as f:
        json.dump(pairs, f, indent=2)

    logger.info(f"扫描完成: 找到 {len(pairs)} 对配对")
    return pairs


# ===== 价差计算 =====

def compute_spread(series_a: np.ndarray, series_b: np.ndarray) -> dict:
    """
    计算两只股票的对数价差和z-score。
    返回：z-score 历史、最新z-score、均值、标准差
    """
    if len(series_a) < 30 or len(series_b) < 30:
        return {"error": "数据不足"}

    min_len = min(len(series_a), len(series_b))
    a = series_a[-min_len:]
    b = series_b[-min_len:]

    # 对数价差
    log_spread = np.log(a) - np.log(b)

    # 计算z-score
    mean = np.mean(log_spread)
    std = np.std(log_spread)
    if std < 0.001:
        std = 0.001  # 防止除零

    zscore = (log_spread - mean) / std

    return {
        "zscore_current": round(float(zscore[-1]), 2),
        "zscore_history": zscore.tolist(),
        "spread_mean": round(float(mean), 4),
        "spread_std": round(float(std), 4),
        "spread_current": round(float(log_spread[-1]), 4),
        "spread_min": round(float(np.min(log_spread)), 4),
        "spread_max": round(float(np.max(log_spread)), 4),
    }


def compute_pair_spread(cache: dict, ticker_a: str, ticker_b: str,
                        window: int = 60) -> dict:
    """计算一对股票的价差和z-score"""
    df_a = cache.get(ticker_a)
    df_b = cache.get(ticker_b)
    if df_a is None or df_b is None:
        return {"error": "数据不足"}

    # 取最近window天的价格
    min_len = min(len(df_a), len(df_b))
    if min_len < window:
        return {"error": "数据不足"}

    a = df_a["Close"].tail(window).values
    b = df_b["Close"].tail(window).values

    spread = compute_spread(a, b)

    # ATR止损
    atr_a = df_a.get("ATR_Pct", np.nan).iloc[-1] if "ATR_Pct" in df_a.columns else 3.0
    atr_b = df_b.get("ATR_Pct", np.nan).iloc[-1] if "ATR_Pct" in df_b.columns else 3.0
    if np.isnan(atr_a): atr_a = 3.0
    if np.isnan(atr_b): atr_b = 3.0

    spread["atr_a"] = round(float(atr_a), 1)
    spread["atr_b"] = round(float(atr_b), 1)
    spread["pair"] = f"{ticker_a}/{ticker_b}"
    spread["tickers"] = [ticker_a, ticker_b]

    return spread


# ===== 信号生成 =====

def generate_pair_signals(cache: dict, pairs: list = None) -> list:
    """为每对配对生成交易信号"""
    cfg = load_config()
    if not cfg.get("enabled", True):
        return []

    if pairs is None:
        # 从缓存加载配对
        if os.path.exists(PAIRS_CACHE):
            with open(PAIRS_CACHE) as f:
                pairs = json.load(f)
        else:
            pairs = scan_pairs(cache)

    if not pairs:
        return []

    zscore_entry = cfg.get("zscore_entry", 1.5)
    zscore_exit = cfg.get("zscore_exit", 0.3)

    signals = []
    for pair in pairs:
        t1, t2 = pair["tickers"]
        spread = compute_pair_spread(cache, t1, t2)
        if "error" in spread:
            continue

        z = spread["zscore_current"]

        # 信号逻辑
        if abs(z) >= zscore_entry:
            if z > zscore_entry:
                # z > 1.5: 价差偏高，卖出t1买入t2
                signal = {
                    "pair": pair["pair"],
                    "action": "SELL_A_BUY_B",
                    "direction": "价差偏高",
                    "sell": t1,
                    "buy": t2,
                    "zscore": z,
                    "threshold": zscore_entry,
                }
            else:
                # z < -1.5: 价差偏低，买入t1卖出t2
                signal = {
                    "pair": pair["pair"],
                    "action": "BUY_A_SELL_B",
                    "direction": "价差偏低",
                    "buy": t1,
                    "sell": t2,
                    "zscore": z,
                    "threshold": -zscore_entry,
                }
            signals.append(signal)
        elif abs(z) < zscore_exit:
            # 价差回归均值，退出信号
            signals.append({
                "pair": pair["pair"],
                "action": "EXIT",
                "direction": "价差回归",
                "zscore": z,
                "threshold": zscore_exit,
            })
        else:
            # 无信号
            signals.append({
                "pair": pair["pair"],
                "action": "HOLD",
                "direction": "等待",
                "zscore": z,
                "threshold": zscore_entry,
            })

    # 按信号强度排序
    signals.sort(key=lambda x: abs(x.get("zscore", 0)), reverse=True)

    return signals


# ===== 综合热图 =====

def get_pairs_heatmap_data(cache: dict, pairs: list = None) -> list:
    """
    生成配对交易热图数据。
    每对配对的色块颜色表示z-score方向和强度。
    """
    signals = generate_pair_signals(cache, pairs)

    results = []
    for sig in signals:
        if sig["action"] in ("SELL_A_BUY_B", "BUY_A_SELL_B", "EXIT"):
            results.append({
                "pair": sig["pair"],
                "action": sig["action"],
                "direction": sig["direction"],
                "zscore": sig["zscore"],
                "sell": sig.get("sell", ""),
                "buy": sig.get("buy", ""),
                "signal_strength": abs(sig["zscore"]),
                "color": "red" if sig["zscore"] > 0 else "green",
            })

    return results


# ===== Web API 兼容 =====

def get_status() -> dict:
    """获取配对交易状态"""
    cfg = load_config()
    signals = []

    if os.path.exists(PAIRS_CACHE):
        with open(PAIRS_CACHE) as f:
            signals = json.load(f)

    return {
        "enabled": cfg.get("enabled", True),
        "pairs_count": len(signals),
        "config": {k: v for k, v in cfg.items() if k != "enabled"},
    }


def get_scan_report() -> dict:
    """获取扫描报告"""
    if os.path.exists(PAIRS_CACHE):
        with open(PAIRS_CACHE) as f:
            pairs = json.load(f)
        return {"pairs": pairs[:20]}
    return {"pairs": []}


if __name__ == "__main__":
    import sys
    from data_prod import load_price_cache

    if "--scan" in sys.argv:
        cache = load_price_cache()
        pairs = scan_pairs(cache)
        print(f"\n找到 {len(pairs)} 对配对:")
        for p in pairs[:20]:
            print(f"  {p['pair']:<20s} 相关系数: {p['correlation']:.4f}")

    elif "--signal" in sys.argv:
        cache = load_price_cache()
        signals = generate_pair_signals(cache)
        print(f"\n配对信号:")
        for s in signals:
            action = "🔴 卖A买B" if s["action"] == "SELL_A_BUY_B" else ("🟢 买A卖B" if s["action"] == "BUY_A_SELL_B" else ("⚪ 平仓" if s["action"] == "EXIT" else "⏳ 等待"))
            print(f"  {s['pair']:<20s} {action} z={s['zscore']:+.2f}")

    elif "--report" in sys.argv:
        cache = load_price_cache()
        signals = generate_pair_signals(cache)
        print(f"\n{'='*60}")
        print(f"  配对交易扫描报告")
        print(f"{'='*60}")
        print(f"  找到 {len(signals)} 对配对")
        active = [s for s in signals if s["action"] in ("SELL_A_BUY_B", "BUY_A_SELL_B")]
        print(f"  有信号: {len(active)} 对")
        for s in active[:10]:
            print(f"    {s['pair']}: {s['direction']} z={s['zscore']:+.2f}")
        print(f"{'='*60}")

    else:
        print("配对交易模块")
        print("  python3 pairs_trading.py --scan     扫描可用配对")
        print("  python3 pairs_trading.py --signal   生成信号")
        print("  python3 pairs_trading.py --report   输出报告")
