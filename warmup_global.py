"""
全量数据预热脚本 — 使用 data_global 新数据源
下载 S&P 500 股票数据，计算技术指标，保存到 pickle 缓存
"""
import logging, os, sys, time, random, gc, pickle
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("warmup")

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# 技术指标计算
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术指标，与 strategy_vector 兼容"""
    if df is None or len(df) < 50:
        return df
    df = df.copy()
    close = df["Close"].astype(float)

    # 均线
    for p in [5, 10, 20, 50, 200]:
        df[f"SMA{p}"] = close.rolling(p).mean()
        df[f"EMA{p}"] = close.ewm(span=p, adjust=False).mean()

    # 动量
    for p in [1, 3, 6, 12]:
        df[f"Momentum_{p}M"] = close.pct_change(periods=p * 21)

    # 波动率
    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean()
    df["ATR_Pct"] = (df["ATR"] / close) * 100

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # 成交量比
    df["Volume_Ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()

    # 布林带
    df["BB_Mid"] = df["SMA20"]
    bb_std = close.rolling(20).std()
    df["BB_Up"] = df["BB_Mid"] + 2 * bb_std
    df["BB_Dn"] = df["BB_Mid"] - 2 * bb_std

    return df


def main():
    from data_global import get_us_tickers, fetch_stock_data

    # 1. 获取股票列表
    tickers = get_us_tickers(min_price=5.0, max_count=200)
    logger.info(f"待下载: {len(tickers)} 只")

    # 2. 逐个下载并计算指标
    cache = {}
    total = len(tickers)

    for i, sym in enumerate(tickers):
        try:
            df = fetch_stock_data(sym, days=730)
            if df is not None and len(df) >= 60:
                df = compute_indicators(df)
                cache[sym] = df
            if (i + 1) % 10 == 0:
                logger.info(f"  [{i+1}/{total}] 成功: {len(cache)} 只")
                save_path = f"{CACHE_DIR}/prices.pkl"
                with open(save_path, "wb") as f:
                    pickle.dump(cache, f)
                logger.info(f"  暂存: {len(cache)} 只")
            # 每只加延迟但不阻塞太久
            time.sleep(random.uniform(0.8, 2.0))
        except Exception as e:
            logger.warning(f"  {sym}: {e}")
            continue
        gc.collect()

    # 3. 最终保存
    save_path = f"{CACHE_DIR}/prices.pkl"
    with open(save_path, "wb") as f:
        pickle.dump(cache, f)
    logger.info(f"✅ 预热完成! 共存 {len(cache)} 只股票")

    # 4. 打印样例
    if "AAPL" in cache:
        df = cache["AAPL"]
        cols = [c for c in df.columns if c not in ["Open","High","Low","Close","Volume","Adj Close"]]
        logger.info(f"AAPL 技术指标: {cols}")


if __name__ == "__main__":
    main()
