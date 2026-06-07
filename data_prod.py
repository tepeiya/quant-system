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
# 价格数据：缓存优先 + 增量更新 + 实时补全
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


def refresh_cache(days_back: int = 10, use_alpaca: bool = True) -> dict:
    """
    实时更新缓存：只补最近 N 天的数据，不重下全部历史。
    优先用Alpaca批量获取（更快），失败回退 yfinance。
    
    Args:
        days_back: 拉取最近多少天的数据用于覆盖缓存（默认10个交易日）
        use_alpaca: 是否优先使用Alpaca
    
    Returns:
        dict: {ticker: 更新行数, ...}
    """
    cache = load_price_cache()
    if not cache:
        logger.warning("缓存为空，请先运行数据预热")
        return {}

    today = datetime.now()
    start_str = (today - timedelta(days=days_back + 10)).strftime("%Y-%m-%d")
    end_str = today.strftime("%Y-%m-%d")
    tickers = list(cache.keys())
    updated = {}

    # Alpaca批量路径
    if use_alpaca:
        try:
            result_batch = {}
            _fetch_alpaca_batch(tickers, result_batch, start_str, end_str)
            for ticker, new_df in result_batch.items():
                if new_df is not None and len(new_df) > 0:
                    old = cache.get(ticker)
                    combined = _merge_dataframes(old, new_df)
                    cache[ticker] = compute_indicators(combined)
                    updated[ticker] = len(new_df)
        except Exception as e:
            logger.warning(f"Alpaca批量刷新失败: {e}，回退单只模式")

    # 回退：单只 yfinance
    remaining = [t for t in tickers if t not in updated]
    if remaining:
        import yfinance as yf
        for i, ticker in enumerate(remaining):
            try:
                t = yf.Ticker(ticker)
                df_new = t.history(start=start_str, end=end_str, auto_adjust=True)
                if df_new is None or len(df_new) == 0:
                    continue
                old = cache.get(ticker)
                combined = _merge_dataframes(old, df_new)
                cache[ticker] = compute_indicators(combined)
                updated[ticker] = len(df_new)
            except Exception as e:
                logger.warning(f"{ticker} 实时更新失败: {str(e)[:60]}")
            if (i+1) % 50 == 0:
                save_price_cache(cache)

    save_price_cache(cache)
    logger.info(f"实时更新完成: {len(updated)}只, 共{sum(updated.values())}行新数据")
    return updated


def _merge_dataframes(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """合并旧数据和新数据，去重、排序、统一时区"""
    if old is None or len(old) == 0:
        return new
    # 统一时区
    for df in [old, new]:
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
    combined = pd.concat([old, new])
    combined = combined[~combined.index.duplicated(keep='last')]
    combined.sort_index(inplace=True)
    return combined


def get_realtime_prices(tickers: list[str]) -> dict[str, float]:
    """
    用Alpaca获取多只股票的最新实时价格（非缓存）。
    用于信号生成前获取最新市价。
    
    Returns:
        dict: {ticker: latest_price, ...}
    """
    from datetime import timezone
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        logger.warning("Alpaca未配置，无法获取实时价格")
        return {}

    try:
        from alpaca.data import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest

        client = StockHistoricalDataClient(KEY, SECRET)
        req = StockLatestQuoteRequest(symbol_or_symbols=tickers)
        quotes = client.get_stock_latest_quote(req)
        result = {}
        for t in tickers:
            q = quotes.get(t)
            if q:
                # 取 bid/ask 中间价作为参考价
                result[t] = round(float(q.ask_price + q.bid_price) / 2, 2)
        return result
    except ImportError:
        logger.warning("alpaca-py未安装")
        return {}
    except Exception as e:
        logger.warning(f"获取实时价格失败: {e}")
        return {}


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
                 use_alpaca: bool = True) -> dict[str, pd.DataFrame]:
    """
    获取价格数据。核心策略：
    1. 从缓存加载所有可用数据
    2. 优先走Alpaca批量获取（快且稳定），失败回退 Tiingo/yfinance
    3. 只对缺失的ticker进行网络请求
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

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

    # 3. Alpaca批量获取（主力数据源）
    if missing:
        alpaca_ok = _fetch_alpaca_batch(missing, result, start, end)
        if alpaca_ok > 0:
            logger.info(f"Alpaca获取: {alpaca_ok}只")
            missing = [t for t in missing if t not in result]

    # 4. yfinance/Tiingo补充（Alpaca失败的）
    if missing:
        logger.info(f"回退yfinance补充: {len(missing)}只")
        import yfinance as yf
        success = 0
        for i, ticker in enumerate(missing):
            try:
                df = yf.download(ticker, start=start, end=end,
                                 progress=False, auto_adjust=True)
                if df is not None and len(df) >= 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    result[ticker] = df
                    success += 1
                    if success % 10 == 0:
                        logger.info(f"  进度[yf]: {success}/{len(missing)}")
                else:
                    logger.warning(f"{ticker}[yf]: 数据不足({len(df) if df is not None else 0}行)")
            except Exception as e:
                logger.warning(f"{ticker}[yf]: {str(e)[:60]}")
                # Tiingo兜底
                tiingo_df = _fetch_tiingo(ticker, start, end)
                if tiingo_df is not None and len(tiingo_df) >= 200:
                    result[ticker] = tiingo_df
                    success += 1

    # 5. 保存缓存
    save_price_cache(result)
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
