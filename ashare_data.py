"""
A股数据服务 (A-Share Data Service)
=================================
支持多种A股数据源：tushare、东方财富、新浪财经

设计原则：
- 统一接口，自动切换数据源（降级机制）
- 数据格式统一为标准OHLCV
- 支持ETF、指数、港股路由
- PIT安全（Point-in-Time）
"""

import os
import sys
import json
import logging
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("quant.ashare")

try:
    import pandas as pd
    import numpy as np
except ImportError:
    pd = None
    np = None

# 配置
CONFIG_FILE = "config/ashare_config.json"

DEFAULT_CONFIG = {
    "primary_source": "tushare",
    "tushare_token": "",
    "fallback_sources": ["eastmoney", "sina", "yfinance"],
    "cache_enabled": True,
    "cache_hours": 4,
    "request_interval": 0.5,
    "max_retries": 3,
}


def load_config() -> Dict:
    """加载A股数据源配置"""
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
        json.dump(config, f, indent=2)


def _get_cache_path(symbol: str, source: str) -> str:
    """获取缓存路径"""
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache", "ashare")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{symbol}_{source}.parquet")


def _is_cache_valid(cache_path: str, hours: int = 4) -> bool:
    """检查缓存是否有效"""
    if not os.path.exists(cache_path):
        return False
    mtime = os.path.getmtime(cache_path)
    return (datetime.now().timestamp() - mtime) < (hours * 3600)


# ============================================================
# 数据源路由
# ============================================================

def _detect_security_type(symbol: str) -> str:
    """检测证券类型：stock / etf / index / hk"""
    symbol = str(symbol).upper()
    
    if re.match(r"^\d{6}\.(SH|SZ)$", symbol):
        code = symbol.split(".")[0]
        if code.startswith(("5", "15", "16", "18", "51", "52", "53", "54", "55")):
            return "etf"
        elif code.startswith(("000", "001", "399")):
            return "index"
        return "stock"
    
    elif re.match(r"^\d{5}\.(HK|HKEX)$", symbol):
        return "hk"
    
    elif re.match(r"^(SH|SZ)\d{6}$", symbol):
        code = symbol[2:]
        if code.startswith(("5", "15", "16", "18", "51", "52", "53", "54", "55")):
            return "etf"
        elif code.startswith(("000", "001", "399")):
            return "index"
        return "stock"
    
    return "stock"


def _normalize_symbol(symbol: str) -> str:
    """统一符号格式为 code.market"""
    symbol = str(symbol).strip().upper()
    
    if "." in symbol:
        return symbol
    
    if re.match(r"^\d{6}$", symbol):
        if symbol.startswith(("6", "5")):
            return f"{symbol}.SH"
        else:
            return f"{symbol}.SZ"
    
    if re.match(r"^SH\d{6}$", symbol):
        return f"{symbol[2:]}.SH"
    
    if re.match(r"^SZ\d{6}$", symbol):
        return f"{symbol[2:]}.SZ"
    
    return symbol


# ============================================================
# Tushare 数据源
# ============================================================

class TushareLoader:
    """Tushare数据加载器"""
    
    def __init__(self, token: str = ""):
        self.token = token or os.environ.get("TUSHARE_TOKEN", "")
        self._pro = None
    
    def _get_pro(self):
        """获取tushare接口"""
        if self._pro is not None:
            return self._pro
        try:
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()
            return self._pro
        except ImportError:
            logger.warning("tushare未安装，请先安装: pip install tushare")
            return None
        except Exception as e:
            logger.warning(f"tushare初始化失败: {e}")
            return None
    
    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """加载日线数据"""
        pro = self._get_pro()
        if pro is None:
            return None
        
        sec_type = _detect_security_type(symbol)
        norm_symbol = _normalize_symbol(symbol)
        ts_code = norm_symbol.replace(".", "")
        
        try:
            if sec_type == "etf":
                df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            elif sec_type == "index":
                df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            elif sec_type == "hk":
                df = pro.hk_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            else:
                df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            
            if df is not None and len(df) > 0:
                df = self._normalize_df(df, symbol)
                return df
            else:
                logger.warning(f"tushare返回空数据: {symbol}")
                return None
        except Exception as e:
            logger.warning(f"tushare加载失败 {symbol}: {e}")
            return None
    
    def _normalize_df(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """标准化数据格式"""
        df = df.rename(columns={
            "ts_code": "symbol",
            "trade_date": "date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "pre_close": "PrevClose",
            "change": "Change",
            "pct_chg": "PctChange",
            "vol": "Volume",
            "amount": "Amount",
        })
        
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        
        df = df.sort_values("date").reset_index(drop=True)
        df["symbol"] = symbol
        
        return df
    
    def get_index_constituents(self, index_code: str = "000300.SH") -> List[str]:
        """获取指数成分股"""
        pro = self._get_pro()
        if pro is None:
            return []
        
        try:
            df = pro.index_weight(index_code=index_code.replace(".", ""))
            if df is not None and len(df) > 0:
                return [f"{code}.SH" if code.startswith("6") else f"{code}.SZ" 
                        for code in df["con_code"].unique()]
        except Exception as e:
            logger.warning(f"获取指数成分股失败: {e}")
        
        return []


# ============================================================
# 东方财富数据源（免费）
# ============================================================

class EastmoneyLoader:
    """东方财富数据加载器（免费）"""
    
    BASE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    
    def __init__(self):
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
        except ImportError:
            self._session = None
    
    def _get_kline_url(self, symbol: str, freq: str = "daily", start_date: str = None, end_date: str = None) -> str:
        """构建K线URL"""
        sec_type = _detect_security_type(symbol)
        norm_symbol = _normalize_symbol(symbol)
        
        if sec_type == "hk":
            market = 116
            code = norm_symbol.split(".")[0]
        elif norm_symbol.endswith(".SH"):
            market = 1
            code = norm_symbol.split(".")[0]
        else:
            market = 0
            code = norm_symbol.split(".")[0]
        
        params = {
            "secid": f"{market}.{code}",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101" if freq == "daily" else "102",
            "fqt": "1",
        }
        
        if start_date:
            params["beg"] = start_date
        if end_date:
            params["end"] = end_date
        
        import urllib.parse
        return f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
    
    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """加载日线数据"""
        if self._session is None:
            return None
        
        try:
            url = self._get_kline_url(symbol, start_date=start_date, end_date=end_date)
            resp = self._session.get(url, timeout=10)
            data = resp.json()
            
            if data.get("data") and data["data"].get("klines"):
                klines = data["data"]["klines"]
                df = pd.DataFrame([k.split(",") for k in klines], 
                                  columns=["date", "Open", "Close", "High", "Low", "Volume", "Amount", "?", "?", "?", "?"])
                
                df["date"] = pd.to_datetime(df["date"])
                df[["Open", "Close", "High", "Low", "Volume", "Amount"]] = df[["Open", "Close", "High", "Low", "Volume", "Amount"]].astype(float)
                df["symbol"] = symbol
                df = df.sort_values("date").reset_index(drop=True)
                
                return df
        except Exception as e:
            logger.warning(f"东方财富加载失败 {symbol}: {e}")
        
        return None


# ============================================================
# 新浪财经数据源（免费）
# ============================================================

class SinaLoader:
    """新浪财经数据加载器（免费）"""
    
    def __init__(self):
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
        except ImportError:
            self._session = None
    
    def load_daily(self, symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """加载日线数据"""
        if self._session is None:
            return None
        
        norm_symbol = _normalize_symbol(symbol)
        market = "sh" if norm_symbol.endswith(".SH") else "sz"
        code = norm_symbol.split(".")[0]
        
        url = f"https://finance.sina.com.cn/stock/api/jsonp.php/var%20json={market}{code}_daily"
        
        try:
            resp = self._session.get(url, timeout=10)
            content = resp.text
            import re
            match = re.search(r"=\s*(\[.*\])", content)
            if match:
                import json
                data = json.loads(match.group(1))
                if data:
                    df = pd.DataFrame(data)
                    df = df.rename(columns={
                        "day": "date",
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume",
                        "amount": "Amount",
                    })
                    df["date"] = pd.to_datetime(df["date"])
                    df["symbol"] = symbol
                    df = df.sort_values("date").reset_index(drop=True)
                    return df
        except Exception as e:
            logger.warning(f"新浪财经加载失败 {symbol}: {e}")
        
        return None


# ============================================================
# 统一数据服务
# ============================================================

class AShareDataService:
    """A股数据统一服务"""
    
    def __init__(self):
        self.config = load_config()
        self._loaders = {
            "tushare": TushareLoader(self.config["tushare_token"]),
            "eastmoney": EastmoneyLoader(),
            "sina": SinaLoader(),
        }
    
    def get_daily_data(self, symbol: str, start_date: str = None, end_date: str = None, 
                       use_cache: bool = True) -> Optional[pd.DataFrame]:
        """获取日线数据（自动切换数据源）"""
        norm_symbol = _normalize_symbol(symbol)
        
        if use_cache and self.config["cache_enabled"]:
            for source in [self.config["primary_source"]] + self.config["fallback_sources"]:
                cache_path = _get_cache_path(norm_symbol, source)
                if _is_cache_valid(cache_path, self.config["cache_hours"]):
                    try:
                        df = pd.read_parquet(cache_path)
                        logger.info(f"  从缓存加载: {norm_symbol} ({source})")
                        return df
                    except:
                        pass
        
        sources_to_try = [self.config["primary_source"]] + self.config["fallback_sources"]
        
        for source_name in sources_to_try:
            loader = self._loaders.get(source_name)
            if loader is None:
                continue
            
            logger.info(f"  尝试从 {source_name} 加载: {norm_symbol}")
            df = loader.load_daily(norm_symbol, start_date, end_date)
            
            if df is not None and len(df) > 0:
                df = _sanitize_ohlc(df)
                
                if use_cache and self.config["cache_enabled"]:
                    try:
                        cache_path = _get_cache_path(norm_symbol, source_name)
                        df.to_parquet(cache_path)
                    except:
                        pass
                
                logger.info(f"  ✓ 成功加载 {len(df)} 条数据")
                return df
            
            time.sleep(self.config["request_interval"])
        
        logger.warning(f"  ✗ 所有数据源加载失败: {norm_symbol}")
        return None
    
    def get_index_constituents(self, index_code: str = "000300.SH") -> List[str]:
        """获取指数成分股"""
        loader = self._loaders.get("tushare")
        if loader:
            result = loader.get_index_constituents(index_code)
            if result:
                return result
        
        return []
    
    def get_multi_daily(self, symbols: List[str], start_date: str = None, end_date: str = None) -> Dict[str, pd.DataFrame]:
        """批量获取多个股票数据"""
        results = {}
        for symbol in symbols:
            df = self.get_daily_data(symbol, start_date, end_date)
            if df is not None:
                results[symbol] = df
            time.sleep(self.config["request_interval"])
        return results


# ============================================================
# OHLC 完整性检查（借鉴Vibe-Trading）
# ============================================================

def _sanitize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """OHLC数据完整性检查与清洗"""
    if df is None or len(df) == 0:
        return df
    
    df = df.copy()
    
    if "Open" in df.columns and "High" in df.columns and "Low" in df.columns and "Close" in df.columns:
        mask = (df["High"] < df["Low"]) | (df["Open"] <= 0) | (df["Close"] <= 0)
        if mask.any():
            logger.warning(f"  发现 {mask.sum()} 条脏数据，已过滤")
            df = df[~mask]
        
        df["Open"] = df.apply(lambda row: min(row["Open"], row["High"]), axis=1)
        df["Close"] = df.apply(lambda row: min(row["Close"], row["High"]), axis=1)
        df["Open"] = df.apply(lambda row: max(row["Open"], row["Low"]), axis=1)
        df["Close"] = df.apply(lambda row: max(row["Close"], row["Low"]), axis=1)
    
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].apply(lambda x: max(0, x))
    
    return df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


# ============================================================
# 便捷函数
# ============================================================

_data_service = None

def get_ashare_service() -> AShareDataService:
    """获取全局A股数据服务实例"""
    global _data_service
    if _data_service is None:
        _data_service = AShareDataService()
    return _data_service


def fetch_ashare(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """便捷获取A股数据"""
    return get_ashare_service().get_daily_data(symbol, start_date, end_date)


def get_csi300_constituents() -> List[str]:
    """获取沪深300成分股"""
    return get_ashare_service().get_index_constituents("000300.SH")


def get_csi500_constituents() -> List[str]:
    """获取中证500成分股"""
    return get_ashare_service().get_index_constituents("000905.SH")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A股数据服务测试")
    parser.add_argument("--symbol", default="000001.SZ", help="股票代码")
    parser.add_argument("--source", default="auto", help="数据源")
    args = parser.parse_args()
    
    service = get_ashare_service()
    df = service.get_daily_data(args.symbol)
    
    if df is not None:
        print(f"成功加载 {args.symbol}")
        print(df.head())
        print(f"\n数据范围: {df['date'].min()} ~ {df['date'].max()}")
        print(f"数据条数: {len(df)}")
    else:
        print(f"加载失败: {args.symbol}")