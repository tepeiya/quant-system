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
    key = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        logger.warning("Alpaca Key未设置，跳过")
        return None

    try:
        from alpaca.data import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

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
        logger.info(f"SPY(Alpaca)已缓存: {len(df)}行, ${df['Close'].iloc[-1]:.2f}")
        return df
    except ImportError:
        logger.warning("alpaca-py未安装，跳过Alpaca数据源")
        return None
    except Exception as e:
        logger.warning(f"fetch_spy(Alpaca)失败: {e}")
        return None


def fetch_spy_yfinance():
    """从yfinance获取SPY数据（免费，无需API Key）"""
    try:
        import yfinance as yf
        t = yf.Ticker("SPY")
        df = t.history(start="2018-01-01", auto_adjust=True)
        if df is None or len(df) < 30:
            logger.warning(f"yfinance SPY数据不足: {len(df) if df is not None else 0}行")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        keep = ["Open", "High", "Low", "Close", "Volume"]
        for col in keep:
            if col not in df.columns:
                df[col] = 0.0
        df = df[keep]
        df.index = pd.to_datetime(df.index)
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        with open(SPY_CACHE, "wb") as f:
            pickle.dump(df, f)
        logger.info(f"SPY(yfinance)已缓存: {len(df)}行, ${df['Close'].iloc[-1]:.2f}")
        return df
    except Exception as e:
        logger.warning(f"fetch_spy_yfinance失败: {e}")
        return None


def fetch_spy_data_global():
    """从data_global获取SPY数据（新浪/Yahoo v8，零鉴权）"""
    try:
        from data_global import fetch_stock_data
        df = fetch_stock_data("SPY", days=730)
        if df is None or len(df) < 30:
            logger.warning(f"data_global SPY数据不足: {len(df) if df is not None else 0}行")
            return None
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        keep = ["Open", "High", "Low", "Close", "Volume"]
        for col in keep:
            if col not in df.columns:
                df[col] = 0.0
        df = df[keep]

        with open(SPY_CACHE, "wb") as f:
            pickle.dump(df, f)
        logger.info(f"SPY(data_global)已缓存: {len(df)}行, ${df['Close'].iloc[-1]:.2f}")
        return df
    except Exception as e:
        logger.warning(f"fetch_spy_data_global失败: {e}")
        return None


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
        if not data or len(data) < 30:
            logger.warning(f"Tiingo SPY数据不足: {len(data) if data else 0}行")
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
    except Exception as e:
        logger.warning(f"fetch_spy_tiingo失败: {e}")
        return None


def get_spy():
    """获取SPY数据（优先缓存 → Alpaca → data_global → yfinance → Tiingo）"""
    if os.path.exists(SPY_CACHE):
        try:
            with open(SPY_CACHE, "rb") as f:
                spy = pickle.load(f)
            if spy is not None and len(spy) > 30:
                return spy
        except Exception:
            pass
    logger.info("SPY缓存缺失，尝试在线获取...")
    # 依次尝试: Alpaca → data_global(零鉴权) → yfinance → Tiingo
    for fetcher_name, fetcher in [
        ("Alpaca", fetch_spy),
        ("data_global", fetch_spy_data_global),
        ("yfinance", fetch_spy_yfinance),
        ("Tiingo", fetch_spy_tiingo),
    ]:
        logger.info(f"  尝试 {fetcher_name} 获取SPY...")
        spy = fetcher()
        if spy is not None and len(spy) > 30:
            return spy
    logger.error("所有SPY数据源均失败")
    return None


if __name__ == "__main__":
    from data_prod import compute_indicators
    spy = get_spy()
    if spy is not None:
        spy = compute_indicators(spy)
        print(f"SPY: {len(spy)}行, ${spy['Close'].iloc[-1]:.2f}")
        print(f"SMA20:{spy['SMA20'].iloc[-1]:.0f} SMA50:{spy['SMA50'].iloc[-1]:.0f} SMA200:{spy['SMA200'].iloc[-1]:.0f}")
        print(f"RSI:{spy['RSI'].iloc[-1]:.0f}")
