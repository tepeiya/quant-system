"""
数据层 - yfinance + pickle 缓存（生产版）
====================================
核心：缓存优先。一次成功获取后永久可用。
增量更新：每天检查缓存最新日期，只补缺失的天数。
重试：指数退避+随机延迟，避免限频。
备选：Tiingo（当yfinance挂时）
"""

import os
import json
import logging
import pickle
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger("quant.data")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")
PRICE_CACHE = f"{CACHE_DIR}/prices.pkl"
FUNDA_CACHE = f"{CACHE_DIR}/fundamentals.pkl"
TICKER_CACHE = f"{CACHE_DIR}/sp500_tickers.json"
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


# ==============================
# S&P 500 成分股
# ==============================
SP500_BUILTIN = sorted([
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
])


def get_tickers() -> list[str]:
    if os.path.exists(TICKER_CACHE):
        try:
            with open(TICKER_CACHE) as f:
                return json.load(f)
        except:
            pass
    # 尝试在线更新
    for url in [
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    ]:
        try:
            if "wikipedia" in url:
                tables = pd.read_html(url, timeout=10)
                tickers = sorted(tables[0]["Symbol"].tolist())
            else:
                r = requests.get(url, timeout=10)
                tickers = sorted([l.split(",")[0] for l in r.text.strip().split("\n")[1:] if l])
            tickers = [t.replace(".", "-") for t in tickers]
            if len(tickers) >= 400:
                with open(TICKER_CACHE, "w") as f:
                    json.dump(tickers, f)
                logger.info(f"成分股: {len(tickers)}只")
                return tickers
        except:
            continue
    logger.info(f"使用内置列表: {len(SP500_BUILTIN)}只")
    return SP500_BUILTIN


# ==============================
# 价格数据：缓存优先 + 增量更新
# ==============================
def load_price_cache() -> dict[str, pd.DataFrame]:
    """从缓存加载，不存在返回空dict。自动计算技术指标。"""
    if os.path.exists(PRICE_CACHE):
        try:
            with open(PRICE_CACHE, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, dict):
                # 自动计算指标（如果没有）
                for t in list(data.keys()):
                    df = data[t]
                    if df is not None and "SMA20" not in df.columns:
                        data[t] = compute_indicators(df)
                return data
        except:
            pass
    return {}


def save_price_cache(data: dict):
    """保存到缓存"""
    with open(PRICE_CACHE, "wb") as f:
        pickle.dump(data, f)
    logger.info(f"缓存已保存: {len(data)}只")


def _fetch_tiingo(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """通过Tiingo API获取单只股票日线数据（带429重试）"""
    api_key = os.environ.get("TIINGO_API_KEY")
    if not api_key:
        return None

    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    params = {
        "startDate": start,
        "endDate": end,
        "format": "json",
        "resampleFreq": "daily",
    }
    headers = {"Authorization": f"Token {api_key}"}

    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Tiingo {ticker}: 429限流，{wait}s后重试")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                logger.warning(f"Tiingo {ticker}: HTTP {r.status_code}")
                return None

            data = r.json()
            if not data or len(data) < 200:
                logger.warning(f"Tiingo {ticker}: 数据不足({len(data) if data else 0}行)")
                return None

            df = pd.DataFrame(data)
            df["Date"] = pd.to_datetime(df["date"])
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)

            df.rename(columns={
                "adjClose": "Close",
                "adjHigh": "High",
                "adjLow": "Low",
                "adjOpen": "Open",
                "adjVolume": "Volume",
            }, inplace=True)

            keep = ["Close", "High", "Low", "Open", "Volume"]
            for col in keep:
                if col not in df.columns:
                    df[col] = 0.0

            df = df[keep]
            df["Close"] = df["Close"].astype(float)
            return df

        except requests.Timeout:
            logger.warning(f"Tiingo {ticker}: 超时")
            continue
        except Exception as e:
            logger.warning(f"Tiingo {ticker}: 异常 {str(e)[:60]}")
            continue

    return None


def fetch_prices(tickers: list[str],
                 start: str = "2018-01-01",
                 end: str = None,
                 max_retries: int = 2,
                 use_alpaca: bool = False) -> dict[str, pd.DataFrame]:
    """
    获取价格数据。核心策略：
    1. 从缓存加载所有可用数据
    2. 只对缺失的ticker进行网络请求
    3. yfinance为主，Tiingo备选，Alpaca可选
    4. 网络请求之间随机延迟防止限流
    
    如果 use_alpaca=True 优先走 Alpaca 批量获取（更快）
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    import yfinance as yf

    # 1. 加载缓存
    cache = load_price_cache()
    result = dict(cache)

    # 2. 识别需要获取的ticker
    missing = []
    for t in tickers:
        if t in result:
            df = result[t]
            if df is not None and len(df) >= 200:
                continue
        missing.append(t)

    if missing:
        logger.info(f"缓存命中{len(result)}只, 需要获取{len(missing)}只")

    # 2.5 Alpaca批量路径（use_alpaca=True时优先）
    if use_alpaca and missing:
        alpaca_ok = _fetch_alpaca_batch(missing, result, start, end)
        if alpaca_ok > 0:
            logger.info(f"Alpaca获取: {alpaca_ok}只")
            missing = [t for t in missing if t not in result]
            if not missing:
                save_price_cache(result)
                return result

    # 3. 网络获取（yfinance -> Tiingo备选）
    success = 0
    yf_rate_limited = False
    for i, ticker in enumerate(missing):
        if yf_rate_limited:
            # 已确认限流，直接用Tiingo
            tiingo_df = _fetch_tiingo(ticker, start, end)
            if tiingo_df is not None and len(tiingo_df) >= 200:
                result[ticker] = tiingo_df
                success += 1
                if success % 10 == 0:
                    logger.info(f"  进度[tiingo]: {success}/{len(missing)}")
            else:
                logger.warning(f"{ticker}[tiingo]: 获取失败，跳过")
            continue

        yf_ok = False
        for attempt in range(max_retries):
            try:
                df = yf.download(ticker, start=start, end=end,
                                 progress=False, auto_adjust=True)
                if df is not None and len(df) >= 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    result[ticker] = df
                    success += 1
                    yf_ok = True
                    if success % 10 == 0:
                        logger.info(f"  进度[yf]: {success}/{len(missing)}")
                    break
                else:
                    logger.warning(f"{ticker}[yf]: 数据不足({len(df) if df is not None else 0}行)")
            except Exception as e:
                err_str = str(e)
                logger.warning(f"{ticker}[yf]: attempt{attempt+1}失败: {err_str[:60]}")
                # 检测限流
                if "RateLimited" in err_str or "429" in err_str or "rate limit" in err_str.lower():
                    logger.warning("yfinance限流，整批切换到Tiingo...")
                    yf_rate_limited = True
                    break
                if attempt < max_retries - 1:
                    delay = 2 ** attempt + random.uniform(1, 3)
                    time.sleep(delay)

        if not yf_ok and not yf_rate_limited:
            # yfinance失败但不是限流 → 单只尝试Tiingo
            tiingo_df = _fetch_tiingo(ticker, start, end)
            if tiingo_df is not None and len(tiingo_df) >= 200:
                result[ticker] = tiingo_df
                success += 1
                logger.info(f"  {ticker}: Tiingo备选 {len(tiingo_df)}行 ✅")
            else:
                logger.warning(f"{ticker}: yfinance+Tiingo均失败，跳过")

        # 每5只之间随机延迟
        if (i + 1) % 5 == 0:
            time.sleep(random.uniform(1, 2))

    # 3.5 对仍缺失的票尝试Alpaca批量补齐（自动）
    unresolved = [t for t in missing if t not in result or result[t] is None or len(result[t]) < 200]
    if unresolved:
        alpaca_ok = _fetch_alpaca_batch(unresolved, result, start, end)
        if alpaca_ok > 0:
            success += alpaca_ok
            logger.info(f"Alpaca补齐: {alpaca_ok}/{len(unresolved)}")

    # 4. 保存缓存
    if missing:
        save_price_cache(result)
        logger.info(f"获取完成: {success}/{len(missing)}")

    return result


# ==============================
# 技术指标（向量化）
# ==============================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """纯NumPy向量化技术指标（兼容仅Close列的情况）"""
    if df is None or len(df) < 250:
        return df
    d = df.copy()
    c = d["Close"].values.astype(float)
    n = len(c)

    # 兼容仅Close列的情况
    if "High" in d.columns:
        h = d["High"].values.astype(float)
        l = d["Low"].values.astype(float)
    else:
        c_shift = np.roll(c, 1); c_shift[0] = c[0]
        volatility = np.std(np.diff(c)) * 0.3
        h = c + np.abs(c - c_shift) + volatility
        l = c - np.abs(c - c_shift) - volatility

    if "Volume" in d.columns:
        v = d["Volume"].values.astype(float)
    else:
        v = np.ones(n) * 1e7

    def _sma(arr, win):
        out = np.full(n, np.nan)
        if n >= win:
            out[win-1:] = pd.Series(arr).rolling(win).mean().values[win-1:]
        return out

    d["SMA20"] = _sma(c, 20)
    d["SMA50"] = _sma(c, 50)
    d["SMA200"] = _sma(c, 200)
    d["PctAbove20"] = (c / d["SMA20"] - 1) * 100
    d["PctAbove50"] = (c / d["SMA50"] - 1) * 100
    d["PctAbove200"] = (c / d["SMA200"] - 1) * 100

    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    d["RSI"] = 100 - (100 / (1 + _sma(gain, 14) / np.maximum(_sma(loss, 14), 1e-10)))

    tr = np.maximum(h - l, np.abs(h - np.roll(c, 1)))
    tr = np.maximum(tr, np.abs(l - np.roll(c, 1)))
    tr[0] = h[0] - l[0]
    d["ATR"] = _sma(tr, 14)
    d["ATR_Pct"] = d["ATR"] / c * 100

    d["Volume_SMA20"] = _sma(v, 20)
    d["Volume_Ratio"] = v / np.maximum(d["Volume_SMA20"], 1)
    d["Momentum_12M"] = d["Close"].pct_change(252)
    d["Momentum_1M_Excl"] = d["Close"].shift(21) / d["Close"].shift(273) - 1
    return d


# ==============================
# 数据校验
# ==============================
def _fetch_alpaca_batch(tickers: list[str], result: dict, start: str, end: str) -> int:
    """Alpaca批量获取价格数据（比Tiingo快）
    注意：免费tier有速率限制
    """
    import pickle as _pkl
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        return 0

    try:
        from alpaca.data import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(KEY, SECRET)
        sd = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ed = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        need = [t for t in tickers if "-" not in t and "." not in t]
        ok = 0
        for i in range(0, len(need), 50):
            batch = need[i:i+50]
            try:
                bars = client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=batch, timeframe=TimeFrame.Day,
                    start=sd, end=ed, limit=5000,
                ))
                df = bars.df
                for t in batch:
                    try:
                        tdf = df.xs(t, level="symbol")[["open","high","low","close","volume"]].copy()
                        tdf.columns = ["Open","High","Low","Close","Volume"]
                        tdf.index = pd.to_datetime(tdf.index)
                        if len(tdf) >= 200:
                            result[t] = compute_indicators(tdf)
                            ok += 1
                    except:
                        pass
            except Exception as e:
                logger.warning(f"Alpaca batch {i}: {str(e)[:60]}")
        return ok
    except ImportError:
        logger.warning("alpaca-py未安装")
        return 0
    except Exception as e:
        logger.warning(f"Alpaca批量获取失败: {str(e)[:60]}")
        return 0


def fetch_fundamentals(tickers: list[str]) -> dict:
    """获取基本面（优先 Finnhub，失败回退 yfinance）"""
    import yfinance as yf
    result = {}
    need = [t for t in tickers if t not in _fundamentals_cache]
    if not need:
        return {t: _fundamentals_cache[t] for t in tickers if t in _fundamentals_cache}

    logger.info(f"获取基本面: {len(need)}只...")

    # 优先 Finnhub
    try:
        from fundamentals_finnhub import _finnhub_get
    except:
        _finnhub_get = None

    for t in need:
        rec = None
        if _finnhub_get:
            rec = _finnhub_get(t)

        # 回退 yfinance
        if not rec:
            try:
                info = yf.Ticker(t).info
                rec = {
                    "pe": info.get("trailingPE") or info.get("forwardPE"),
                    "roe": info.get("returnOnEquity"),
                    "profit_margin": info.get("profitMargins"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "market_cap": info.get("marketCap"),
                    "dividend_yield": info.get("dividendYield"),
                    "earnings_date": info.get("earningsDate"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "source": "yfinance",
                }
            except:
                rec = {}

        result[t] = rec
        _fundamentals_cache[t] = rec

    # 缓存到磁盘
    try:
        import pickle as _pkl
        with open(os.path.join(CACHE_DIR, "fundamentals.pkl"), "wb") as f:
            _pkl.dump(_fundamentals_cache, f)
    except:
        pass

    return result


# 基本面缓存
_fundamentals_cache = {}
_fundamentals_cache_file = os.path.join(CACHE_DIR, "fundamentals.pkl")
if os.path.exists(_fundamentals_cache_file):
    try:
        import pickle as _pkl
        with open(_fundamentals_cache_file, "rb") as f:
            _fundamentals_cache = _pkl.load(f)
    except:
        pass


def validate(data: dict[str, pd.DataFrame]) -> dict:
    issues = []
    clean = 0
    for t, df in data.items():
        if df is None or len(df) < 200:
            issues.append(f"{t}: {len(df) if df is not None else 0}行")
            continue
        na = df["Close"].isna().sum() / len(df)
        if na > 0.05:
            issues.append(f"{t}: Close缺失{na*100:.0f}%")
            continue
        clean += 1
    return {
        "total": len(data), "clean": clean, "issues": len(issues),
        "issue_list": issues[:10],
        "pass_pct": f"{clean/max(len(data),1)*100:.0f}%",
    }
