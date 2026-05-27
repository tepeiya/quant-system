"""
价值因子缓存工具 - 批量获取全S&P 500的PE/PB
==========================================
使用：python3 fetch_value_factors.py
在电脑上跑（yfinance不限频），一次性获取后永久缓存。

输出：data_cache/pe_ratios.pkl
      data_cache/pb_ratios.pkl
"""

import logging
import os
import pickle
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("quant.value")

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
PE_CACHE = f"{CACHE_DIR}/pe_ratios.pkl"

# 候选池
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
    "MMC","CB","APD","SHW","ECL","ROST","CTAS","ITW","BF.B",
]


def load_existing():
    if os.path.exists(PE_CACHE):
        with open(PE_CACHE, "rb") as f:
            return pickle.load(f)
    return {}


def fetch_pe(tickers: list[str]) -> dict:
    """批量获取PE，带缓存和断点续传"""
    import yfinance as yf
    result = load_existing()
    need = [t for t in tickers if t not in result]
    
    if not need:
        logger.info(f"全部已缓存: {len(result)}只")
        return result
    
    logger.info(f"需获取: {len(need)}只")
    success = 0
    for i, ticker in enumerate(need):
        try:
            info = yf.Ticker(ticker).info
            pe = info.get("trailingPE")
            pb = info.get("priceToBook")
            result[ticker] = {"pe": pe, "pb": pb}
            success += 1
        except Exception as e:
            logger.warning(f"{ticker}: {str(e)[:50]}")
            result[ticker] = {"pe": None, "pb": None}
        
        if (i + 1) % 20 == 0:
            logger.info(f"  进度: {i+1}/{len(need)} ({success}成功)")
            with open(PE_CACHE, "wb") as f:
                pickle.dump(result, f)
            time.sleep(1)
    
    with open(PE_CACHE, "wb") as f:
        pickle.dump(result, f)
    
    valid = sum(1 for v in result.values() if v.get("pe") and v["pe"] > 0)
    logger.info(f"完成: {len(result)}只, 有PE: {valid}只")
    return result


def get_value_score(ticker: str, pe_cache: dict = None) -> float:
    """
    获取价值因子评分 (0-15分)
    PE < 15 → 15分（低估）
    PE 15-20 → 10分（合理偏低）
    PE 20-25 → 5分（合理偏高）
    PE > 25 → 0分（高估）
    None → 5分（未知）
    """
    if pe_cache is None:
        pe_cache = load_existing()
    data = pe_cache.get(ticker, {})
    pe = data.get("pe") if data else None
    if pe is None or pe <= 0:
        return 5  # 未知，给中性分
    if pe < 15:
        return 15
    elif pe < 20:
        return 10
    elif pe < 25:
        return 5
    else:
        return 0


if __name__ == "__main__":
    fetch_pe(TICKERS)
    
    # 测试
    cache = load_existing()
    valid = [(t, d) for t, d in cache.items() if d.get("pe") and d["pe"] > 0]
    valid.sort(key=lambda x: x[1]["pe"])
    print("\n最低PE Top10（最便宜）:")
    for t, d in valid[:10]:
        print(f"  {t:6s}: PE={d['pe']:.1f}, PB={d.get('pb','?'):.1f}")
    print("\n最高PE Top10（最贵）:")
    for t, d in valid[-10:]:
        print(f"  {t:6s}: PE={d['pe']:.1f}, PB={d.get('pb','?'):.1f}")
