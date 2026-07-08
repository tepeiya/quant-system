"""
多资产数据模块
============
扩充系统支持以下资产：
- TLT (20年以上美国国债) — 避险/利率下降时涨
- GLD (黄金ETF) — 通胀/避险
- DBC (商品ETF) — 通胀/经济过热
- SHY (1-3年国债) — 现金等价物
- VNQ (房地产REITs) — 不动产

用法：
  python3 multi_asset.py                    # 拉取数据+回测
  python3 multi_asset.py --signal            # 输出多资产信号
"""

import logging
import os
import pickle
from datetime import datetime
import time
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("quant.multi")

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
MULTI_CACHE = f"{CACHE_DIR}/multi_asset.pkl"

# 资产配置
# 每类资产的代码、名称、和风险等级
ASSETS = {
    "SPY": {"name": "美股大盘", "risk": "成长", "proxy_for": "equity"},
    "TLT": {"name": "长债", "risk": "避险", "proxy_for": "bond_long"},
    "IEF": {"name": "中债", "risk": "避险", "proxy_for": "bond_mid"},
    "SHY": {"name": "短债", "risk": "现金", "proxy_for": "cash"},
    "GLD": {"name": "黄金", "risk": "对冲", "proxy_for": "gold"},
    "DBC": {"name": "商品", "risk": "通胀", "proxy_for": "commodity"},
    "VNQ": {"name": "房地产", "risk": "成长", "proxy_for": "realestate"},
}


def fetch_multi_asset(start="2018-01-01", end=None):
    """获取所有资产的历史数据（优先data_global，yfinance备选）"""
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    cache = {}
    if os.path.exists(MULTI_CACHE):
        with open(MULTI_CACHE, "rb") as f:
            cache = pickle.load(f)
        logger.info(f"缓存命中: {len(cache)}只")

    need = [s for s in ASSETS if s not in cache]
    if not need:
        logger.info("全部已缓存")
        return cache

    for sym in need:
        df = None
        try:
            from data_global import fetch_stock_data
            df = fetch_stock_data(sym, days=730)
            if df is not None and len(df) > 200:
                logger.info(f"  {sym}: data_global {len(df)}行")
                cache[sym] = df
                continue
        except Exception:
            pass

        for attempt in range(2):
            try:
                df = yf.download(sym, start=start, end=end,
                                 progress=False, auto_adjust=True)
                if df is not None and len(df) > 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    cache[sym] = df
                    logger.info(f"  {sym}: yfinance {len(df)}行")
                    break
            except Exception as e:
                logger.warning(f"  {sym}: attempt {attempt+1}: {str(e)[:50]}")
                time.sleep(1 + random.random() * 2)

    with open(MULTI_CACHE, "wb") as f:
        pickle.dump(cache, f)
    logger.info(f"缓存保存: {len(cache)}只")
    return cache


def compute_momentum(ticker_data: pd.DataFrame, lookback=63) -> float:
    """计算某个资产过去N天的动量"""
    close = ticker_data["Close"].values
    if len(close) < lookback:
        return 0
    return (close[-1] / close[-lookback] - 1) * 100


def multi_asset_signal(cache: dict = None) -> dict:
    """
    多资产轮动信号。
    逻辑：每月检查一次，持有动量最强的2个资产。
    类似 Meb Faber 的 GTAA 策略。
    """
    if cache is None:
        if os.path.exists(MULTI_CACHE):
            with open(MULTI_CACHE, "rb") as f:
                cache = pickle.load(f)
        else:
            cache = fetch_multi_asset()

    # 计算每个资产的1月/3月/6月动量
    results = []
    for sym, info in ASSETS.items():
        df = cache.get(sym)
        if df is None or len(df) < 126:
            continue
        mom_1m = compute_momentum(df, 21)
        mom_3m = compute_momentum(df, 63)
        mom_6m = compute_momentum(df, 126)

        # 综合动量分（3个月权重最大）
        avg_mom = mom_1m * 0.3 + mom_3m * 0.5 + mom_6m * 0.2
        results.append({
            "symbol": sym,
            "name": info["name"],
            "risk": info["risk"],
            "mom_1m": round(mom_1m, 1),
            "mom_3m": round(mom_3m, 1),
            "mom_6m": round(mom_6m, 1),
            "avg_mom": round(avg_mom, 1),
        })

    df = pd.DataFrame(results)
    if df.empty:
        return {"top2": [], "all": []}
    df = df.sort_values("avg_mom", ascending=False)

    # 动量为正且排名前2的资产
    positive_mom = df[df["avg_mom"] > 0]
    top2 = positive_mom.head(2)
    bottom = df.tail(len(df) - 2)

    print(f"\n{'='*65}")
    print(f"  多资产轮动信号")
    print(f"  {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*65}")
    print(f"{'代码':>6} {'名称':<10} {'类型':<6} {'1月%':>7} {'3月%':>7} {'6月%':>7} {'综合分':>7}")
    print(f"{'-'*55}")
    for _, r in df.iterrows():
        flag = "🟢" if r["symbol"] in top2["symbol"].values else ""
        print(f"{r['symbol']:>6} {r['name']:<10} {r['risk']:<6} "
              f"{r['mom_1m']:>+6.1f}% {r['mom_3m']:>+6.1f}% {r['mom_6m']:>+6.1f}% "
              f"{r['avg_mom']:>+6.1f}% {flag}")

    print(f"\n建议配置:")
    if not top2.empty:
        for _, r in top2.iterrows():
            print(f"  50% {r['name']} ({r['symbol']}) — 动量{r['avg_mom']:+.1f}%")
        print(f"  剩余仓位: 现金/SHY")
    else:
        print(f"  全仓: 现金/SHY（所有资产动量为负）")

    # 股票vs债券偏好
    if "SPY" in top2["symbol"].values:
        print(f"\n📈 股票偏好: 偏多")
        print(f"  建议持股仓位提高")
    elif "TLT" in top2["symbol"].values or "IEF" in top2["symbol"].values:
        print(f"\n📉 债券偏好: 避险")
        print(f"  建议减少股票仓位，增加债券")
    elif "GLD" in top2["symbol"].values:
        print(f"\n🥇 黄金偏好: 对冲")
        print(f"  通胀预期上升，注意仓位控制")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "rankings": df.to_dict("records"),
        "top2": top2["symbol"].tolist() if not top2.empty else ["SHY"],
    }


def run_multi_asset_backtest():
    """多资产轮动简单回测"""
    cache = fetch_multi_asset()
    spy = yf.download("SPY", start="2020-01-01", end=datetime.now().strftime("%Y-%m-%d"),
                      progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    # 每月1日检查
    start = "2020-01-01"
    dates = pd.bdate_range(start, datetime.now(), freq="BMS")  # 月初
    spy_close = spy["Close"]

    equity = [10000]
    for i, d in enumerate(dates):
        # 用该日期前的最新数据计算动量
        cache_sub = {}
        for sym in ASSETS:
            df = cache.get(sym)
            if df is not None:
                idx = df.index.get_indexer([d], method="nearest")
                if idx[0] >= 0 and idx[0] < len(df):
                    cache_sub[sym] = df.iloc[:idx[0]+1]

        if len(cache_sub) < 3:
            continue

        signal = multi_asset_signal(cache_sub)
        top2 = signal.get("top2", ["SHY", "SHY"])

        # 模拟收益（持有2只等权）
        d_next = dates[i+1] if i+1 < len(dates) else datetime.now()
        returns = []
        for sym in top2:
            df = cache.get(sym)
            if df is None:
                continue
            idx_start = df.index.get_indexer([d], method="nearest")[0]
            idx_end = df.index.get_indexer([d_next], method="nearest")[0]
            if idx_start >= 0 and idx_end >= 0 and idx_end < len(df):
                ret = (df["Close"].iloc[idx_end] / df["Close"].iloc[idx_start] - 1)
                returns.append(ret)

        if returns:
            equity.append(equity[-1] * (1 + np.mean(returns)))

    eq = pd.Series(equity, index=dates[:len(equity)])
    total = (eq.iloc[-1] / eq.iloc[0] - 1) * 100

    spy_ret = (spy_close.iloc[-1] / spy_close.iloc[0] - 1) * 100

    print(f"\n{'='*55}")
    print(f"  多资产轮动回测 (2020 ~ 现在)")
    print(f"{'='*55}")
    print(f"  策略收益: {total:+.1f}%")
    print(f"  SPY买入持有: {spy_ret:+.1f}%")
    print(f"  策略回撤: 需详细计算")

    return eq


if __name__ == "__main__":
    if "--signal" in __import__("sys").argv:
        multi_asset_signal()
    else:
        multi_asset_signal()
        run_multi_asset_backtest()
