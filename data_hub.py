"""
统一数据源管理器 (Unified Data Source Manager)
==============================================
整合 Vibe-Trading 的 6 大核心数据源，支持自动降级和智能路由

数据源清单：
1. Tushare   - A股价格、财务报表、财务指标（需Token，AKShare免费降级）
2. AKShare   - A股/港股/美股/期货/外汇（免费聚合）
3. yfinance  - 港股/美股/ETF/指数（免费）
4. OKX       - 加密货币（免费）
5. CCXT      - 100+加密货币交易所（免费）
6. Futu      - 港股/A股（需本地OpenD）

设计原则：
- 统一 OHLCV 输出格式
- 自动检测证券类型并路由到最优数据源
- 主源失败自动降级到备选源
- PIT安全（Point-in-Time）
"""

import os
import sys
import json
import logging
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union

logger = logging.getLogger("quant.data_hub")

try:
    import pandas as pd
    import numpy as np
except ImportError:
    pd = None
    np = None


# ============================================================
# 配置
# ============================================================

CONFIG_FILE = "config/data_hub_config.json"

DEFAULT_CONFIG = {
    "source_priority": {
        "ashare": ["tushare", "akshare", "eastmoney", "sina"],
        "us": ["data_global", "yfinance", "akshare"],
        "hk": ["yfinance", "futu", "tushare"],
        "crypto": ["okx", "ccxt"],
        "futures": ["akshare", "tushare"],
        "forex": ["akshare", "yfinance"],
    },
    "tushare_token": "",
    "futu_open_d_host": "127.0.0.1",
    "futu_open_d_port": 11111,
    "cache_enabled": True,
    "cache_hours": 4,
    "request_interval": 0.3,
    "max_retries": 3,
    "timeout": 15,
}


def load_config() -> Dict:
    """加载数据源配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            pass
    return DEFAULT_CONFIG


def save_config(config: Dict):
    """保存配置"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ============================================================
# 证券类型检测
# ============================================================

def detect_market(symbol: str) -> str:
    """
    检测证券所属市场
    返回: ashare / us / hk / crypto / futures / forex
    """
    symbol = str(symbol).upper().strip()

    # 加密货币
    if any(symbol.endswith(s) for s in ["USDT", "USDC", "BUSD", "BTC", "ETH"]) or \
       "-" in symbol and any(x in symbol for x in ["BTC", "ETH", "SOL", "BNB"]):
        return "crypto"

    # 外汇
    if re.match(r"^[A-Z]{6}$", symbol) or re.match(r"^[A-Z]{3}/[A-Z]{3}$", symbol) or \
       symbol in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]:
        return "forex"

    # 期货（常见期货代码）
    if any(symbol.startswith(p) for p in ["CL", "GC", "SI", "NG", "ZC", "ZS", "ZW"]) or \
       re.match(r"^[A-Z]{1,3}[0-9]{1,4}$", symbol):
        return "futures"

    # A股（6位数字 + .SH/.SZ）
    if re.match(r"^\d{6}\.(SH|SZ)$", symbol) or re.match(r"^(SH|SZ)\d{6}$", symbol):
        return "ashare"

    # 港股（5位数字 + .HK）
    if re.match(r"^\d{5}\.HK$", symbol) or re.match(r"^\d{4,5}$", symbol) and len(symbol) <= 5:
        return "hk"

    # 美股（字母代码）
    if re.match(r"^[A-Z]{1,6}$", symbol):
        return "us"

    return "us"  # 默认


def normalize_symbol(symbol: str, market: str = None) -> str:
    """标准化符号格式"""
    symbol = str(symbol).strip().upper()
    if market is None:
        market = detect_market(symbol)

    if market == "ashare":
        if "." in symbol:
            return symbol
        if re.match(r"^\d{6}$", symbol):
            return f"{symbol}.SH" if symbol.startswith(("6", "5")) else f"{symbol}.SZ"
        if re.match(r"^SH\d{6}$", symbol):
            return f"{symbol[2:]}.SH"
        if re.match(r"^SZ\d{6}$", symbol):
            return f"{symbol[2:]}.SZ"

    elif market == "hk":
        if "." in symbol:
            return symbol
        if re.match(r"^\d{4,5}$", symbol):
            return f"{symbol}.HK"

    return symbol


# ============================================================
# 数据源基类
# ============================================================

class BaseLoader:
    """数据源加载器基类"""

    name = "base"
    markets = []
    requires_api_key = False

    def __init__(self, config: Dict):
        self.config = config

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """加载日线数据，返回标准化 OHLCV DataFrame"""
        raise NotImplementedError

    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return True

    def _normalize_ohlcv(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """标准化为统一的 OHLCV 格式"""
        if df is None or len(df) == 0:
            return df

        df = df.copy()

        # 统一列名
        rename_map = {
            "open": "Open", "Open": "Open",
            "high": "High", "High": "High",
            "low": "Low", "Low": "Low",
            "close": "Close", "Close": "Close",
            "volume": "Volume", "Volume": "Volume", "vol": "Volume",
            "amount": "Amount", "Amount": "Amount",
            "date": "date", "datetime": "date", "trade_date": "date", "time": "date",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # 确保日期格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # 确保数值类型
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # OHLC完整性检查
        required = ["Open", "High", "Low", "Close"]
        if all(c in df.columns for c in required):
            mask = (df["High"] < df["Low"]) | (df["Open"] <= 0) | (df["Close"] <= 0)
            if mask.any():
                df = df[~mask]
            # 修正价格边界
            df["Open"] = df.apply(lambda r: min(max(r["Open"], r["Low"]), r["High"]), axis=1)
            df["Close"] = df.apply(lambda r: min(max(r["Close"], r["Low"]), r["High"]), axis=1)

        if "Volume" in df.columns:
            df["Volume"] = df["Volume"].clip(lower=0)

        df["symbol"] = symbol
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).sort_values("date").reset_index(drop=True)
        return df


# ============================================================
# 1. Tushare 数据源
# ============================================================

class TushareLoader(BaseLoader):
    name = "tushare"
    markets = ["ashare", "hk"]
    requires_api_key = True

    def __init__(self, config: Dict):
        super().__init__(config)
        self.token = config.get("tushare_token", "") or os.environ.get("TUSHARE_TOKEN", "")
        self._pro = None

    def is_available(self) -> bool:
        return bool(self.token)

    def _get_pro(self):
        if self._pro is not None:
            return self._pro
        try:
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()
            return self._pro
        except ImportError:
            logger.debug("tushare未安装")
            return None
        except Exception as e:
            logger.debug(f"tushare初始化失败: {e}")
            return None

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        pro = self._get_pro()
        if pro is None:
            return None

        try:
            from ashare_data import _detect_security_type
            norm = normalize_symbol(symbol, "ashare")
            ts_code = norm.replace(".", "")
            sec_type = _detect_security_type(norm)

            if sec_type == "etf":
                df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            elif sec_type == "index":
                df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            else:
                df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

            if df is not None and len(df) > 0:
                df = df.rename(columns={
                    "ts_code": "symbol", "trade_date": "date",
                    "vol": "Volume", "pct_chg": "PctChange",
                })
                return self._normalize_ohlcv(df, symbol)
        except Exception as e:
            logger.debug(f"tushare加载失败 {symbol}: {e}")
        return None


# ============================================================
# 2. AKShare 数据源（免费聚合）
# ============================================================

class AKShareLoader(BaseLoader):
    name = "akshare"
    markets = ["ashare", "hk", "us", "futures", "forex"]
    requires_api_key = False

    def is_available(self) -> bool:
        try:
            import akshare
            return True
        except ImportError:
            return False

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            market = detect_market(symbol)

            if market == "ashare":
                norm = normalize_symbol(symbol, "ashare")
                code = norm.split(".")[0]
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                if df is not None and len(df) > 0:
                    df = df.rename(columns={"日期": "date", "开盘": "Open", "收盘": "Close",
                                            "最高": "High", "最低": "Low", "成交量": "Volume", "成交额": "Amount"})
                    return self._normalize_ohlcv(df, symbol)

            elif market == "hk":
                code = symbol.replace(".HK", "").replace(".hk", "")
                df = ak.stock_hk_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                if df is not None and len(df) > 0:
                    df = df.rename(columns={"日期": "date", "开盘": "Open", "收盘": "Close",
                                            "最高": "High", "最低": "Low", "成交量": "Volume"})
                    return self._normalize_ohlcv(df, symbol)

            elif market == "us":
                df = ak.stock_us_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                if df is not None and len(df) > 0:
                    df = df.rename(columns={"日期": "date", "开盘": "Open", "收盘": "Close",
                                            "最高": "High", "最低": "Low", "成交量": "Volume"})
                    return self._normalize_ohlcv(df, symbol)

            elif market == "futures":
                df = ak.futures_zh_daily_sina(symbol=symbol)
                if df is not None and len(df) > 0:
                    return self._normalize_ohlcv(df, symbol)

        except Exception as e:
            logger.debug(f"akshare加载失败 {symbol}: {e}")
        return None


# ============================================================
# 3. yfinance 数据源（港股/美股）
# ============================================================

class YFinanceLoader(BaseLoader):
    name = "yfinance"
    markets = ["us", "hk", "forex"]
    requires_api_key = False

    def is_available(self) -> bool:
        try:
            import yfinance
            return True
        except ImportError:
            return False

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf

            yf_symbol = symbol
            market = detect_market(symbol)
            if market == "hk":
                code = symbol.replace(".HK", "").replace(".hk", "")
                yf_symbol = f"{int(code):04d}.HK"

            period = "max"
            df = yf.download(yf_symbol, start=start_date, end=end_date, period=period if not start_date else None, progress=False)

            if df is not None and len(df) > 0:
                df = df.reset_index()
                if "Date" in df.columns:
                    df = df.rename(columns={"Date": "date"})
                return self._normalize_ohlcv(df, symbol)
        except Exception as e:
            logger.debug(f"yfinance加载失败 {symbol}: {e}")
        return None


# ============================================================
# 4. OKX 数据源（加密货币）
# ============================================================

class OKXLoader(BaseLoader):
    name = "okx"
    markets = ["crypto"]
    requires_api_key = False

    BASE_URL = "https://www.okx.com/api/v5/market"

    def __init__(self, config: Dict):
        super().__init__(config)
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        except ImportError:
            self._session = None

    def is_available(self) -> bool:
        return self._session is not None

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        if self._session is None:
            return None

        try:
            inst_id = symbol.upper().replace("-", "-")
            url = f"{self.BASE_URL}/history-candles"
            params = {"instId": inst_id, "bar": "1D", "limit": "300"}

            if start_date:
                ts = int(pd.Timestamp(start_date).timestamp() * 1000)
                params["before"] = str(ts)
            if end_date:
                ts = int(pd.Timestamp(end_date).timestamp() * 1000)
                params["after"] = str(ts)

            resp = self._session.get(url, params=params, timeout=self.config.get("timeout", 15))
            data = resp.json()

            if data.get("code") == "0" and data.get("data"):
                rows = data["data"]
                df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume", "Amount", "?", "?"])
                df["date"] = pd.to_datetime(df["ts"].astype(int), unit="ms")
                df = df.drop(columns=["ts", "?"])
                for col in ["Open", "High", "Low", "Close", "Volume", "Amount"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return self._normalize_ohlcv(df, symbol)
        except Exception as e:
            logger.debug(f"okx加载失败 {symbol}: {e}")
        return None


# ============================================================
# 5. CCXT 数据源（100+加密交易所）
# ============================================================

class CCXTLoader(BaseLoader):
    name = "ccxt"
    markets = ["crypto"]
    requires_api_key = False

    def __init__(self, config: Dict):
        super().__init__(config)
        self._exchange = None
        self.exchange_name = config.get("ccxt_exchange", "binance")

    def is_available(self) -> bool:
        try:
            import ccxt
            return True
        except ImportError:
            return False

    def _get_exchange(self):
        if self._exchange is not None:
            return self._exchange
        try:
            import ccxt
            self._exchange = getattr(ccxt, self.exchange_name)({"enableRateLimit": True})
            return self._exchange
        except Exception as e:
            logger.debug(f"ccxt初始化失败: {e}")
            return None

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        exchange = self._get_exchange()
        if exchange is None:
            return None

        try:
            market = detect_market(symbol)
            if market != "crypto":
                return None

            ccxt_symbol = symbol.upper().replace("-", "/")

            since = None
            if start_date:
                since = int(pd.Timestamp(start_date).timestamp() * 1000)

            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe="1d", since=since, limit=1000)

            if ohlcv:
                df = pd.DataFrame(ohlcv, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
                df["date"] = pd.to_datetime(df["ts"], unit="ms")
                df = df.drop(columns=["ts"])

                if end_date:
                    df = df[df["date"] <= pd.Timestamp(end_date)]

                return self._normalize_ohlcv(df, symbol)
        except Exception as e:
            logger.debug(f"ccxt加载失败 {symbol}: {e}")
        return None


# ============================================================
# 6. Futu 数据源（富途，港股/A股）
# ============================================================

class FutuLoader(BaseLoader):
    name = "futu"
    markets = ["hk", "ashare"]
    requires_api_key = False  # 需要本地OpenD

    def __init__(self, config: Dict):
        super().__init__(config)
        self.host = config.get("futu_open_d_host", "127.0.0.1")
        self.port = config.get("futu_open_d_port", 11111)

    def is_available(self) -> bool:
        try:
            from futu import OpenQuoteContext
            return True
        except ImportError:
            return False

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        try:
            from futu import OpenQuoteContext, KLType, AUTYPE

            market = detect_market(symbol)
            if market not in ["hk", "ashare"]:
                return None

            if market == "hk":
                futu_code = f"HK.{symbol.replace('.HK', '').replace('.hk', '')}"
            else:
                norm = normalize_symbol(symbol, "ashare")
                code = norm.split(".")[0]
                futu_code = f"SH.{code}" if norm.endswith(".SH") else f"SZ.{code}"

            quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
            try:
                ret, df, _ = quote_ctx.request_history_kline(
                    futu_code, start=start_date or "", end=end_date or "",
                    ktype=KLType.K_DAY, autype=AUTYPE.FQ_HFQ, max_count=1000
                )
                if ret == 0 and df is not None and len(df) > 0:
                    df = df.rename(columns={
                        "time_key": "date", "open": "Open", "close": "Close",
                        "high": "High", "low": "Low", "volume": "Volume", "turnover": "Amount"
                    })
                    return self._normalize_ohlcv(df, symbol)
            finally:
                quote_ctx.close()
        except Exception as e:
            logger.debug(f"futu加载失败 {symbol}: {e}")
        return None


# ============================================================
# 7. DataGlobal 数据源（零鉴权，新浪/Yahoo v8/东财）
# ============================================================

class DataGlobalLoader(BaseLoader):
    name = "data_global"
    markets = ["us", "hk"]
    requires_api_key = False

    def is_available(self) -> bool:
        try:
            from data_global import fetch_stock_data
            return True
        except ImportError:
            return False

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        try:
            from data_global import fetch_stock_data
            market = detect_market(symbol)
            if market not in ["us", "hk"]:
                return None
            # data_global 内部会尝试新浪 → Yahoo 多源降级
            df = fetch_stock_data(symbol, days=730)
            if df is not None and len(df) > 0:
                return self._normalize_ohlcv(df, symbol)
        except Exception as e:
            logger.debug(f"data_global加载失败 {symbol}: {e}")
        return None


# ============================================================
# 统一数据源管理器
# ============================================================

class DataHub:
    """统一数据源管理器"""

    def __init__(self, config: Dict = None):
        self.config = config or load_config()
        self._loaders = {
            "tushare": TushareLoader(self.config),
            "akshare": AKShareLoader(self.config),
            "yfinance": YFinanceLoader(self.config),
            "okx": OKXLoader(self.config),
            "ccxt": CCXTLoader(self.config),
            "futu": FutuLoader(self.config),
            "data_global": DataGlobalLoader(self.config),
        }

    def get_available_sources(self) -> Dict[str, Dict]:
        """获取所有可用数据源状态"""
        result = {}
        for name, loader in self._loaders.items():
            result[name] = {
                "available": loader.is_available(),
                "markets": loader.markets,
                "requires_api_key": loader.requires_api_key,
            }
        return result

    def get_sources_for_symbol(self, symbol: str) -> List[str]:
        """根据符号获取适用的数据源列表（按优先级排序）"""
        market = detect_market(symbol)
        priority = self.config["source_priority"].get(market, [])
        return [s for s in priority if s in self._loaders and self._loaders[s].is_available()]

    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None,
                   use_cache: bool = True) -> Optional[pd.DataFrame]:
        """加载日线数据（自动路由 + 降级）"""
        market = detect_market(symbol)
        sources = self.get_sources_for_symbol(symbol)

        if not sources:
            logger.warning(f"  ✗ 无可用数据源: {symbol} (市场: {market})")
            return None

        # 缓存检查
        if use_cache and self.config["cache_enabled"]:
            cached = self._load_cache(symbol)
            if cached is not None:
                logger.info(f"  📦 从缓存加载: {symbol}")
                return cached

        # 依次尝试数据源
        for source_name in sources:
            loader = self._loaders[source_name]
            logger.info(f"  尝试 {source_name} 加载: {symbol}")
            try:
                df = loader.load_daily(symbol, start_date, end_date)
                if df is not None and len(df) > 0:
                    logger.info(f"  ✓ {source_name} 成功加载 {len(df)} 条数据")
                    if use_cache and self.config["cache_enabled"]:
                        self._save_cache(symbol, df)
                    return df
            except Exception as e:
                logger.debug(f"  ✗ {source_name} 失败: {e}")
            time.sleep(self.config["request_interval"])

        logger.warning(f"  ✗ 所有数据源加载失败: {symbol}")
        return None

    def load_multi(self, symbols: List[str], start_date: str = None, end_date: str = None) -> Dict[str, pd.DataFrame]:
        """批量加载"""
        results = {}
        for sym in symbols:
            df = self.load_daily(sym, start_date, end_date)
            if df is not None:
                results[sym] = df
        return results

    def _get_cache_path(self, symbol: str) -> str:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache", "hub")
        os.makedirs(cache_dir, exist_ok=True)
        safe_name = re.sub(r"[^\w\-.]", "_", symbol)
        return os.path.join(cache_dir, f"{safe_name}.parquet")

    def _load_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self._get_cache_path(symbol)
        if not os.path.exists(path):
            return None
        mtime = os.path.getmtime(path)
        if (datetime.now().timestamp() - mtime) > (self.config["cache_hours"] * 3600):
            return None
        try:
            return pd.read_parquet(path)
        except:
            return None

    def _save_cache(self, symbol: str, df: pd.DataFrame):
        try:
            df.to_parquet(self._get_cache_path(symbol))
        except:
            pass

    def get_source_info(self) -> Dict:
        """获取数据源详细信息"""
        return {
            "sources": self.get_available_sources(),
            "source_priority": self.config["source_priority"],
            "total_sources": len(self._loaders),
            "available_count": sum(1 for l in self._loaders.values() if l.is_available()),
        }


# ============================================================
# 便捷函数
# ============================================================

_hub = None

def get_data_hub() -> DataHub:
    """获取全局 DataHub 实例"""
    global _hub
    if _hub is None:
        _hub = DataHub()
    return _hub


def fetch(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """便捷获取数据（自动路由到最优数据源）"""
    return get_data_hub().load_daily(symbol, start_date, end_date)


def fetch_multi(symbols: List[str], start_date: str = None, end_date: str = None) -> Dict[str, pd.DataFrame]:
    """批量获取数据"""
    return get_data_hub().load_multi(symbols, start_date, end_date)


def list_sources() -> Dict[str, Dict]:
    """列出所有数据源状态"""
    return get_data_hub().get_available_sources()


if __name__ == "__main__":
    print("=" * 60)
    print("  统一数据源管理器 (Data Hub)")
    print("=" * 60)

    hub = get_data_hub()
    info = hub.get_source_info()

    print(f"\n数据源总数: {info['total_sources']}")
    print(f"可用数据源: {info['available_count']}")
    print("\n数据源状态:")
    for name, status in info["sources"].items():
        icon = "✅" if status["available"] else "❌"
        key = " (需API Key)" if status["requires_api_key"] else " (免费)"
        markets = ", ".join(status["markets"])
        print(f"  {icon} {name:12s}{key:15s} 市场: {markets}")

    print("\n市场路由优先级:")
    for market, sources in info["source_priority"].items():
        print(f"  {market:8s}: {' → '.join(sources)}")

    # 测试
    print("\n" + "=" * 60)
    print("测试数据加载:")
    test_symbols = ["AAPL", "000001.SZ", "0700.HK", "BTC-USDT"]
    for sym in test_symbols:
        market = detect_market(sym)
        sources = hub.get_sources_for_symbol(sym)
        print(f"\n  {sym} (市场: {market})")
        print(f"    可用数据源: {sources}")
