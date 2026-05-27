"""
增量数据更新工具
==============
用法：python3 data_update.py
功能：
1. 从缓存加载现有数据
2. 检查哪些ticker需要更新（最新日期 < 今日-2天）
3. 用Alpaca获取缺失数据，失败回退到yfinance
4. 保存到缓存
"""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pickle
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("quant.update")

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache/prices.pkl")

TICKERS = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA",
    "AVGO","AMD","INTC","QCOM","TXN","ASML","AMAT","KLAC","LRCX","MU",
    "ORCL","CRM","ADBE","NOW","WDAY","PANW","CRWD","ADP",
    "NFLX","UBER","ABNB",
    "JPM","GS","BK","AXP","V","MA","BLK","C","BAC","MS","SCHW",
    "COST","WMT","HD","LOW","MCD","SBUX","NKE","TJX","TGT",
    "JNJ","UNH","LLY","MRK","ABBV","PFE","AMGN","ISRG","SYK","VRTX",
    "CAT","DE","BA","LMT","RTX","GE","HON","MMM","ETN","TDG",
    "XOM","CVX","COP","EOG","SLB","OXY",
    "T","VZ","CMCSA","DIS",
    "PG","KO","PEP","CL","KMB","MDLZ","SYY",
    "NEE","DUK","SO","D","AEP","SRE",
    "UPS","FDX","CSX","UNP",
    "MMC","CB","APD","SHW","ECL","ROST","CTAS","ITW",
    "BF-B","BRK-B",
]
CLEAN_TICKERS = [t for t in TICKERS if "-" not in t and "." not in t]


def update():
    ts = datetime.now()

    # 1. 加载缓存
    cache = {}
    if Path(CACHE).exists():
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    logger.info(f"缓存: {len(cache)}只")

    # 2. 找需要更新的（最新数据 < 昨天）
    today = datetime.now().date()
    yesterday = today - timedelta(days=2)
    need_update = []
    need_new = []

    for t in TICKERS:
        if t in cache and cache[t] is not None:
            last_date = cache[t].index[-1].date() if hasattr(cache[t].index[-1], 'date') else cache[t].index[-1]
            if last_date < yesterday:
                need_update.append(t)
        else:
            need_new.append(t)

    logger.info(f"需更新: {len(need_update)}只, 新增: {len(need_new)}只")

    if not need_update and not need_new:
        logger.info("所有数据最新，无需更新")
        return len(cache)

    # 3. Alpaca更新
    updated = 0
    try:
        from alpaca.data import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        import os

        key = os.environ.get("ALPACA_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if key and secret:
            client = StockHistoricalDataClient(key, secret)
            # 更新已有ticker
            to_fetch = [t for t in need_update if t in CLEAN_TICKERS]
            if to_fetch:
                for i in range(0, len(to_fetch), 50):
                    batch = to_fetch[i:i+50]
                    try:
                        bars = client.get_stock_bars(StockBarsRequest(
                            symbol_or_symbols=batch,
                            timeframe=TimeFrame.Day,
                            start=datetime(2020, 1, 1).replace(tzinfo=timezone.utc),
                            end=datetime.now().replace(tzinfo=timezone.utc),
                            limit=5000,
                        ))
                        df = bars.df
                        for ticker in batch:
                            try:
                                tdf = df.xs(ticker, level="symbol")[["open","high","low","close","volume"]].copy()
                                tdf.columns = ["Open","High","Low","Close","Volume"]
                                tdf.index = pd.to_datetime(tdf.index)
                                if len(tdf) >= 200:
                                    cache[ticker] = tdf
                                    updated += 1
                            except:
                                pass
                        logger.info(f"  Alpaca: +{len(batch)}")
                    except Exception as e:
                        logger.warning(f"  Alpaca batch失败: {e}")
    except ImportError:
        logger.info("Alpaca SDK未安装")

    # 4. yfinance补充（Alpaca失败的）
    remaining = [t for t in need_new+need_update if t not in cache or t in need_update]
    if remaining:
        logger.info(f"yfinance补充: {len(remaining)}只")
        import yfinance as yf
        for t in remaining:
            try:
                df = yf.download(t, start="2020-01-01", end=today.strftime("%Y-%m-%d"),
                                 progress=False, auto_adjust=True)
                if df is not None and len(df) >= 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    cache[t] = df
                    updated += 1
            except Exception as e:
                logger.warning(f"  {t}: {str(e)[:50]}")
            time.sleep(0.3)

    # 5. 保存
    if updated > 0:
        with open(CACHE, "wb") as f:
            pickle.dump(cache, f)
        logger.info(f"已保存: {len(cache)}只 (+{updated})")
    else:
        logger.info("无新数据")

    elapsed = (datetime.now()-ts).total_seconds()
    logger.info(f"耗时: {elapsed:.1f}s")
    return len(cache)


if __name__ == "__main__":
    update()
