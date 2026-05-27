"""
SPY 数据源解决
=============
方案：
1. 用Alpaca免费tier直接拉SPY（已确认可用）
2. 拉取后缓存到 data_cache/spy_real.pkl
3. 以后 daily_signal.py / web 面板全部用真实SPY
"""

import os
import pickle
import logging
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger("quant.spy")

SPY_CACHE = "data_cache/spy_real.pkl"


def fetch_spy():
    """从Alpaca获取真实SPY数据"""
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    key = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        logger.warning("Alpaca Key未设置")
        return None

    client = StockHistoricalDataClient(key, secret)
    bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=["SPY"],
        timeframe=TimeFrame.Day,
        start=datetime(2018, 1, 1).replace(tzinfo=timezone.utc),
        end=datetime.now().replace(tzinfo=timezone.utc),
        limit=5000,
    ))
    df = bars.df.xs("SPY", level="symbol")[["open", "high", "low", "close", "volume"]].copy()
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    df.index = pd.to_datetime(df.index)

    with open(SPY_CACHE, "wb") as f:
        pickle.dump(df, f)
    logger.info(f"SPY已缓存: {len(df)}行, ${df['Close'].iloc[-1]:.2f}")
    return df


def fetch_spy_tiingo():
    """从Tiingo获取SPY数据（Alpaca备选）"""
    import requests
    api_key = os.environ.get("TIINGO_API_KEY")
    if not api_key:
        return None
    url = "https://api.tiingo.com/tiingo/daily/SPY/prices"
    params = {"startDate": "2018-01-01", "endDate": datetime.now().strftime("%Y-%m-%d"),
              "format": "json", "resampleFreq": "daily"}
    headers = {"Authorization": f"Token {api_key}"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or len(data) < 200:
            return None
        df = pd.DataFrame(data)
        df["Date"] = pd.to_datetime(df["date"])
        df.set_index("Date", inplace=True)
        df.sort_index(inplace=True)
        df["Close"] = df["adjClose"].astype(float)
        df["High"] = df["adjHigh"].astype(float)
        df["Low"] = df["adjLow"].astype(float)
        df["Open"] = df["adjOpen"].astype(float)
        df["Volume"] = df["adjVolume"].astype(float)
        df = df[["Close", "High", "Low", "Open", "Volume"]]
        with open(SPY_CACHE, "wb") as f:
            pickle.dump(df, f)
        logger.info(f"SPY(Tiingo)已缓存: {len(df)}行, ${df['Close'].iloc[-1]:.2f}")
        return df
    except:
        return None


def get_spy():
    """获取SPY数据（优先缓存 → Tiingo，跳过yfinance）"""
    if os.path.exists(SPY_CACHE):
        with open(SPY_CACHE, "rb") as f:
            spy = pickle.load(f)
        if spy is not None and len(spy) > 100:
            return spy
    logger.info("SPY缓存缺失，使用Tiingo获取...")
    return fetch_spy_tiingo()


if __name__ == "__main__":
    from data_prod import compute_indicators
    spy = get_spy()
    if spy is not None:
        spy = compute_indicators(spy)
        print(f"SPY: {len(spy)}行, ${spy['Close'].iloc[-1]:.2f}")
        print(f"SMA20:{spy['SMA20'].iloc[-1]:.0f} SMA50:{spy['SMA50'].iloc[-1]:.0f} SMA200:{spy['SMA200'].iloc[-1]:.0f}")
        print(f"RSI:{spy['RSI'].iloc[-1]:.0f}")
