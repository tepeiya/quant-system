"""
全球股票数据层 — 整合 global-stock-data 的 5 个零鉴权数据源
=================================================
数据源：新浪财经 (HTTP)、腾讯财经 (HTTPS)、东方财富 push2 (HTTPS)、Yahoo Finance (v8 零 crumb)、SEC EDGAR
覆盖：美股 + 港股 · 行情 · K线 · 基本面 · 资金流 · 期权 · SEC Filing
全部零鉴权，仅依赖 requests

整合方式：
  - 替换 data_prod.py 中的 yfinance 数据获取
  - 保持 load_price_cache() / compute_indicators() / get_tickers() 接口不变
  - 缓存依然走 pickle，与现有系统完全兼容
"""

import os, json, time, re, requests, logging, hashlib
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("quant.data_global")

# ==============================
# Yahoo Finance Session (零 crumb)
# ==============================

_YAHOO_SESSION = None
_YAHOO_CRUMB = None
_YAHOO_COOKIE = None


def _get_yahoo_session() -> requests.Session:
    """获取 Yahoo Finance session，自动管理 cookie + crumb"""
    global _YAHOO_SESSION, _YAHOO_CRUMB, _YAHOO_COOKIE
    if _YAHOO_SESSION is not None:
        return _YAHOO_SESSION

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    })
    # 获取 cookie
    r = s.get("https://fc.yahoo.com/", timeout=10)
    # 获取 crumb
    r2 = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
    if r2.status_code == 200:
        _YAHOO_CRUMB = r2.text.strip()
    else:
        # 备用：从页面提取
        r3 = s.get("https://finance.yahoo.com/", timeout=10)
        m = re.search(r'"crumb":"([^"]+)"', r3.text)
        if m:
            _YAHOO_CRUMB = m.group(1)
    _YAHOO_SESSION = s
    logger.debug(f"Yahoo session 初始化完成, crumb={'有' if _YAHOO_CRUMB else '无'}")
    return s


# ==============================
# 新浪财经 — 美股行情
# ==============================

def us_quote_sina(ticker: str) -> dict:
    """美股实时行情（新浪 36 字段）"""
    url = f"https://hq.sinajs.cn/list=gb_{ticker.lower()}"
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        text = r.text.strip()
        m = re.search(r'"(.+)"', text)
        if not m:
            return {}
        fields = m.group(1).split(",")
        if len(fields) < 30:
            return {}
        return {
            "symbol": ticker,
            "name": fields[0],
            "price": float(fields[1]) if fields[1] else 0,
            "change_pct": float(fields[2]) if fields[2] else 0,
            "prev_close": float(fields[26]) if len(fields) > 26 and fields[26] else 0,
            "open": float(fields[5]) if len(fields) > 5 and fields[5] else 0,
            "high": float(fields[6]) if len(fields) > 6 and fields[6] else 0,
            "low": float(fields[7]) if len(fields) > 7 and fields[7] else 0,
            "volume": float(fields[10]) if len(fields) > 10 and fields[10] else 0,
            "market_cap": float(fields[22]) if len(fields) > 22 and fields[22] else 0,
            "eps": float(fields[29]) if len(fields) > 29 and fields[29] else 0,
            "pe": float(fields[31]) if len(fields) > 31 and fields[31] else 0,
            "source": "sina",
        }
    except Exception:
        return {}


def us_kline_sina(ticker: str, num: int = 120) -> list[dict]:
    """美股日K线（新浪，可回溯到1984年）"""
    url = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK"
    params = {"symbol": ticker.upper(), "num": num}
    try:
        r = requests.get(url, params=params,
                         headers={"Referer": "https://finance.sina.com.cn/",
                                  "User-Agent": "Mozilla/5.0"},
                         timeout=15)
        text = r.text
        m = re.search(r'\((\[.+\])\)', text)
        if not m:
            return []
        import json as _json
        items = _json.loads(m.group(1))
        result = []
        for item in items:
            result.append({
                "date": item.get("d"),
                "open": float(item.get("o", 0)),
                "high": float(item.get("h", 0)),
                "low": float(item.get("l", 0)),
                "close": float(item.get("c", 0)),
                "volume": int(item.get("v", 0)),
            })
        return result
    except Exception:
        return []


# ==============================
# 腾讯财经 — 美股/港股行情 (字段最全)
# ==============================

def us_quote_tencent(ticker: str) -> dict:
    """美股实时行情（腾讯 71 字段，最全面）"""
    url = f"https://qt.gtimg.cn/q=us{ticker}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.encoding = "gbk"
        text = r.text.strip()
        if '=' not in text or '"' not in text:
            return {}
        parts = text.split('"')[1].split('~') if '"' in text else []
        if len(parts) < 45:
            return {}
        def _v(i, t=float, d=0):
            try: return t(parts[i]) if i < len(parts) and parts[i] else d
            except: return d
        return {
            "symbol": ticker,
            "name": _v(1, str, ""),
            "code": _v(2, str, ""),
            "price": _v(3),
            "pre_close": _v(4),
            "open": _v(5),
            "volume": _v(6, int),
            "bid": _v(7),
            "ask": _v(8),
            "high": _v(9),
            "low": _v(10),
            "change": _v(31),
            "change_pct": _v(32),
            "pe": _v(37),
            "amplitude": _v(43),
            "turnover_rate": _v(38),
            "market_cap": _v(45),
            "total_shares": _v(46),
            "pb": _v(47),
            "eps": _v(49),
            "dividend": _v(51),
            "source": "tencent",
        }
    except Exception:
        return {}


def hk_quote_tencent(code: str) -> dict:
    """港股实时行情（腾讯 78 字段）"""
    # code 格式: 00700 (不含 HK 后缀)
    url = f"https://qt.gtimg.cn/q=r_hk{code}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.encoding = "gbk"
        text = r.text.strip()
        if '=' not in text or '"' not in text:
            return {}
        parts = text.split('"')[1].split('~') if '"' in text else []
        if len(parts) < 50:
            return {}
        def _v(i, t=float, d=0):
            try: return t(parts[i]) if i < len(parts) and parts[i] else d
            except: return d
        return {
            "symbol": code,
            "name": _v(1, str, ""),
            "code": f"HK{code}",
            "price": _v(3),
            "pre_close": _v(4),
            "open": _v(5),
            "volume": _v(6, int),
            "high": _v(33),
            "low": _v(34),
            "change": _v(31),
            "change_pct": _v(32),
            "pe": _v(39),
            "market_cap": _v(45),
            "pb": _v(50),
            "eps": _v(52),
            "dividend": _v(55),
            "source": "tencent_hk",
        }
    except Exception:
        return {}


# ==============================
# 东方财富 — 行情/基本面/资金流
# ==============================

def get_secid(ticker_or_code: str, market: str = "us") -> int:
    """获取东方财富 secid 前缀"""
    prefix_map = {"us": 105, "hk": 106, "a_sh": 1}
    return prefix_map.get(market, 105)


def quote_eastmoney(ticker: str, market: str = "us") -> dict:
    """东方财富实时行情"""
    secid = get_secid(ticker, market)
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}.{ticker}"
           f"&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        d = data.get("data", {})
        if not d:
            return {}
        return {
            "symbol": ticker,
            "name": d.get("f58", ""),
            "price": d.get("f43", 0) / 100 if d.get("f43") else 0,
            "high": d.get("f44", 0) / 100 if d.get("f44") else 0,
            "low": d.get("f45", 0) / 100 if d.get("f45") else 0,
            "open": d.get("f46", 0) / 100 if d.get("f46") else 0,
            "pre_close": d.get("f47", 0) / 100 if d.get("f47") else 0,
            "volume": d.get("f48", 0),
            "amount": d.get("f50", 0),
            "change_pct": d.get("f170", 0) / 100 if d.get("f170") else 0,
            "turnover_rate": d.get("f168", 0) / 100 if d.get("f168") else 0,
            "pe": d.get("f162", 0) / 100 if d.get("f162") else 0,
            "amplitude": d.get("f167", 0) / 100 if d.get("f167") else 0,
            "market_cap": d.get("f116", 0),
            "total_shares": d.get("f117", 0),
            "pb": d.get("f60", 0) / 100 if d.get("f60") else 0,
            "source": "eastmoney",
        }
    except Exception:
        return {}


def fund_flow_daily(ticker: str, market: str = "us", days: int = 5) -> list[dict]:
    """日级资金流向（东方财富）"""
    secid = get_secid(ticker, market)
    url = (f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?"
           f"secid={secid}.{ticker}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56"
           f"&klt=101&lmt={days}")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        klines = data.get("data", {}).get("klines", [])
        result = []
        for k in klines:
            parts = k.split(",")
            if len(parts) >= 6:
                result.append({
                    "date": parts[0],
                    "main_net": float(parts[1]),
                    "large_net": float(parts[2]),
                    "medium_net": float(parts[3]),
                    "small_net": float(parts[4]),
                    "total_net": float(parts[5]),
                })
        return result
    except Exception:
        return []


def financial_statements(sec_code: str, statement: str = "balance", market: str = "us") -> list[dict]:
    """财报三表（东方财富，中文科目）"""
    secid = get_secid(None, market)
    # sec_code 是东方财富的 secucode
    report_map = {"balance": "SUMMARY", "income": "INCOME", "cashflow": "CASHFLOW"}
    report_name = report_map.get(statement, "SUMMARY")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           f"reportName=RPT_DMSK_FN_{report_name}"
           f"&columns=ALL&filter=(SECUCODE%3D%22{sec_code}%22)"
           f"&pageSize=8&sortColumns=REPORT_DATE&sortTypes=-1&source=HSF&client=PC")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json().get("data", [])
    except Exception:
        return []


def stock_search(keyword: str, count: int = 10) -> list[dict]:
    """搜索股票（东财，中英文均可）"""
    url = f"https://searchadapter.eastmoney.com/api/suggest/get?"
    url += f"input={requests.utils.quote(keyword)}&count={count}&type=14"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.json().get("quotes", [])
    except Exception:
        return []


def market_stock_list(market: str = "us", sort_field: str = "f3", sort_dir: str = "desc",
                      page: int = 1, page_size: int = 100) -> list[dict]:
    """全市场股票列表（东财 push2）"""
    secid_prefix = 105 if market == "us" else 106
    fs = f"m:{secid_prefix}+t:2" if market == "us" else f"m:{secid_prefix}+t:1"
    url = (f"https://push2.eastmoney.com/api/qt/clist/get?"
           f"pn={page}&pz={page_size}&po={1 if sort_dir=='desc' else 0}&np=1"
           f"&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f100"
           f"&fs={fs}&fid={sort_field}")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("diff", [])
        result = []
        for d in items:
            result.append({
                "symbol": d.get("f12", ""),
                "name": d.get("f14", ""),
                "price": d.get("f2", 0),
                "change_pct": d.get("f3", 0),
                "change": d.get("f4", 0),
                "volume": d.get("f5", 0),
                "amount": d.get("f6", 0),
                "amplitude": d.get("f7", 0),
                "turnover_rate": d.get("f8", 0),
                "high": d.get("f15", 0),
                "low": d.get("f16", 0),
                "open": d.get("f17", 0),
                "pre_close": d.get("f18", 0),
                "market_cap": d.get("f20", 0),
                "total_shares": d.get("f21", 0),
                "pe": d.get("f23", 0),
                "pb": d.get("f24", 0),
            })
        return result
    except Exception:
        return []


# ==============================
# Yahoo Finance — K线/基本面/期权
# ==============================

def kline_yahoo(symbol: str, interval: str = "1d", range_: str = "2y") -> list[dict]:
    """Yahoo chart K线（v8 API，零crumb）"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
    try:
        s = _get_yahoo_session()
        r = s.get(url, timeout=15)
        data = r.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        adjclose = result.get("indicators", {}).get("adjclose", [{}])[0]
        opens = quotes.get("open", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        volumes = quotes.get("volume", [])
        adjcloses = adjclose.get("adjclose", []) if adjclose else []
        klines = []
        for i, ts in enumerate(timestamps):
            if i < len(closes) and closes[i] is not None:
                klines.append({
                    "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "open": opens[i] if i < len(opens) else 0,
                    "high": highs[i] if i < len(highs) else 0,
                    "low": lows[i] if i < len(lows) else 0,
                    "close": closes[i],
                    "volume": volumes[i] if i < len(volumes) else 0,
                    "adjclose": adjcloses[i] if i < len(adjcloses) and adjcloses[i] is not None else 0,
                })
        return klines
    except Exception:
        return []


def quote_summary_yahoo(symbol: str, modules: Optional[list[str]] = None) -> dict:
    """Yahoo 综合财务数据"""
    if modules is None:
        modules = ["price", "summaryDetail", "financialData", "defaultKeyStatistics"]
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules={','.join(modules)}"
    try:
        s = _get_yahoo_session()
        r = s.get(url, timeout=15)
        return r.json().get("quoteSummary", {}).get("result", [{}])[0]
    except Exception:
        return {}


def options_chain(symbol: str) -> dict:
    """Yahoo 期权链"""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{symbol}"
    try:
        s = _get_yahoo_session()
        r = s.get(url, timeout=15)
        data = r.json().get("optionChain", {}).get("result", [{}])[0]
        return {
            "expirations": data.get("expirationDates", []),
            "calls": data.get("options", [{}])[0].get("calls", []),
            "puts": data.get("options", [{}])[0].get("puts", []),
        }
    except Exception:
        return {}


# ==============================
# 技术指标计算（纯Python）
# ==============================

def calc_ma(klines: list[dict], periods: list[int] = None) -> list[dict]:
    """移动平均线"""
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = [k.get("close", 0) or 0 for k in klines]
    result = []
    for i, k in enumerate(klines):
        k = dict(k)
        for p in periods:
            if i + 1 >= p:
                k[f"MA{p}"] = round(sum(closes[i+1-p:i+1]) / p, 2)
            else:
                k[f"MA{p}"] = None
        result.append(k)
    return result


def calc_macd(klines: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    """MACD 指标"""
    closes = [k.get("close", 0) or 0 for k in klines]

    def _ema(data, period):
        result = []
        multiplier = 2 / (period + 1)
        for i, v in enumerate(data):
            if i == 0:
                result.append(v)
            else:
                result.append((v - result[-1]) * multiplier + result[-1])
        return result

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [ef - es for ef, es in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    hist = [(d - de) * 2 for d, de in zip(dif, dea)]

    result = []
    for i, k in enumerate(klines):
        k = dict(k)
        k["DIF"] = round(dif[i], 3) if i < len(dif) else 0
        k["DEA"] = round(dea[i], 3) if i < len(dea) else 0
        k["MACD"] = round(hist[i], 3) if i < len(hist) else 0
        result.append(k)
    return result


def calc_rsi(klines: list[dict], periods: list[int] = None) -> list[dict]:
    """RSI 指标"""
    if periods is None:
        periods = [6, 12, 24]
    closes = [k.get("close", 0) or 0 for k in klines]
    result = []
    for i, k in enumerate(klines):
        k = dict(k)
        for p in periods:
            if i < p:
                k[f"RSI{p}"] = None
                continue
            gains, losses = 0, 0
            for j in range(i - p + 1, i + 1):
                diff = closes[j] - closes[j - 1]
                if diff > 0:
                    gains += diff
                else:
                    losses -= diff
            avg_gain = gains / p
            avg_loss = losses / p
            if avg_loss == 0:
                k[f"RSI{p}"] = 100
            else:
                rs = avg_gain / avg_loss
                k[f"RSI{p}"] = round(100 - (100 / (1 + rs)), 2)
        result.append(k)
    return result


def calc_kdj(klines: list[dict], n: int = 9) -> list[dict]:
    """KDJ 指标"""
    result = []
    k_val, d_val = 50, 50
    for i, k in enumerate(klines):
        k = dict(k)
        if i + 1 < n:
            k["K"], k["D"], k["J"] = None, None, None
            result.append(k)
            continue
        high_n = max(klines[j].get("high", 0) or 0 for j in range(i + 1 - n, i + 1))
        low_n = min(klines[j].get("low", 0) or 0 for j in range(i + 1 - n, i + 1))
        close = k.get("close", 0) or 0
        if high_n == low_n:
            rsv = 50
        else:
            rsv = (close - low_n) / (high_n - low_n) * 100
        k_val = 2/3 * k_val + 1/3 * rsv
        d_val = 2/3 * d_val + 1/3 * k_val
        j_val = 3 * k_val - 2 * d_val
        k["K"] = round(k_val, 2)
        k["D"] = round(d_val, 2)
        k["J"] = round(j_val, 2)
        result.append(k)
    return result


def calc_boll(klines: list[dict], period: int = 20) -> list[dict]:
    """布林带指标"""
    closes = [k.get("close", 0) or 0 for k in klines]
    result = []
    for i, k in enumerate(klines):
        k = dict(k)
        if i + 1 < period:
            k["BOLL_UP"], k["BOLL_MID"], k["BOLL_DN"] = None, None, None
            result.append(k)
            continue
        ma = sum(closes[i + 1 - period:i + 1]) / period
        std = (sum((c - ma) ** 2 for c in closes[i + 1 - period:i + 1]) / period) ** 0.5
        k["BOLL_MID"] = round(ma, 2)
        k["BOLL_UP"] = round(ma + 2 * std, 2)
        k["BOLL_DN"] = round(ma - 2 * std, 2)
        result.append(k)
    return result


# ==============================
# 全市场股票列表（替代 get_tickers）
# ==============================

def get_us_tickers(min_price: float = 5.0, max_count: int = 500) -> list[str]:
    """从东财获取美股全部股票列表"""
    # 内置 S&P 500（东财可能受限于网络）
    default_tickers = ["AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AVGO","AMD",
                        "QCOM","TXN","ORCL","CRM","ADBE","NOW","PANW","NFLX","JPM","GS",
                        "V","MA","BLK","BAC","MS","COST","WMT","HD","MCD","SBUX","NKE",
                        "JNJ","UNH","LLY","MRK","ABBV","PFE","AMGN","CAT","BA","GE",
                        "HON","XOM","CVX","COP","T","VZ","DIS","PG","KO","PEP","NEE",
                        "UPS","MMC","CB","APD"]
    try:
        stocks = market_stock_list(market="us", sort_field="f3", sort_dir="desc",
                                    page=1, page_size=200)
        if stocks and len(stocks) > 10:
            result = []
            for s in stocks:
                sym = s.get("symbol", "")
                price = s.get("price", 0)
                if sym and sym.isalpha() and len(sym) <= 5 and (price >= min_price or price == 0):
                    result.append(sym)
            if len(result) >= 50:
                return sorted(set(result))[:max_count]
    except:
        pass
    return sorted(set(default_tickers))[:max_count]


# ==============================
# 缓存与 DataFrame 格式兼容层
# ==============================

def klines_to_dataframe(klines: list[dict]) -> "pd.DataFrame":
    """将 kline dict 列表转换为 pandas DataFrame（与 data_prod 缓存格式兼容）"""
    import pandas as pd
    df = pd.DataFrame(klines)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume", "adjclose": "Adj Close",
    })
    # 确保列名与原有格式一致
    for col in ["Open", "High", "Low", "Close", "Volume", "Adj Close"]:
        if col not in df.columns:
            df[col] = 0
    df = df[["Open", "High", "Low", "Close", "Volume", "Adj Close"]]
    df = df.sort_index()
    return df


def fetch_stock_data(symbol: str, days: int = 730) -> "pd.DataFrame | None":
    """
    统一接口：获取单只股票历史数据
    优先走新浪（更快），回退 Yahoo
    返回 pandas DataFrame 格式，与 data_prod 缓存兼容
    """
    # 先试新浪 K 线
    days_needed = max(days, 120)
    klines = us_kline_sina(symbol, num=min(days_needed, 2000))
    if klines and len(klines) >= 20:
        df = klines_to_dataframe(klines)
        if not df.empty and len(df) >= 20:
            return df
    # 回退 Yahoo
    klines = kline_yahoo(symbol, interval="1d", range_="2y")
    if klines and len(klines) >= 20:
        df = klines_to_dataframe(klines)
        if not df.empty and len(df) >= 20:
            return df
    return None


def fetch_batch_data(tickers: list[str], days: int = 730,
                     progress_callback=None) -> dict:
    """
    批量获取多只股票数据
    返回 {ticker: DataFrame} 字典，与 data_prod.load_price_cache() 格式兼容
    """
    import random, gc
    result = {}
    total = len(tickers)
    for i, sym in enumerate(tickers):
        try:
            df = fetch_stock_data(sym, days=days)
            if df is not None:
                result[sym] = df
            if progress_callback and (i + 1) % 20 == 0:
                progress_callback(i + 1, total, len(result))
        except Exception:
            pass
        # 请求间隔避免限频
        if (i + 1) % 10 == 0:
            time.sleep(random.uniform(0.3, 1.0))
    return result
