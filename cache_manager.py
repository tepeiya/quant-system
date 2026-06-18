"""
缓存管理 — 自动检查过期并刷新
==============================
- 检查缓存是否超过7天
- 过期自动重新预热
- 每日daemon调用一次
"""

import os, pickle, json, logging
from datetime import datetime, timedelta

logger = logging.getLogger("quant.cache")

CACHE_DIR = "data_cache"
PRICE_CACHE = f"{CACHE_DIR}/prices.pkl"
TICKER_CACHE = f"{CACHE_DIR}/sp500_tickers.json"
CACHE_META = f"{CACHE_DIR}/cache_meta.json"


def check_cache_health() -> dict:
    """检查缓存健康状况"""
    result = {"status": "ok", "age_days": 0, "stock_count": 0, "needs_refresh": False}

    if not os.path.exists(PRICE_CACHE):
        result["status"] = "empty"
        result["needs_refresh"] = True
        return result

    # 检查缓存时间
    mtime = os.path.getmtime(PRICE_CACHE)
    age = (datetime.now() - datetime.fromtimestamp(mtime)).days
    result["age_days"] = age

    # 加载缓存
    try:
        with open(PRICE_CACHE, "rb") as f:
            data = pickle.load(f)
        result["stock_count"] = len(data)
    except:
        result["status"] = "corrupted"
        result["needs_refresh"] = True
        return result

    if age > 7:
        result["status"] = "stale"
        result["needs_refresh"] = True
    elif age > 3:
        result["status"] = "aging"

    return result


def refresh_if_needed() -> bool:
    """如果需要则自动刷新缓存"""
    health = check_cache_health()
    if not health["needs_refresh"]:
        logger.info(f"缓存健康: {health['stock_count']}只, {health['age_days']}天前")
        return False

    logger.info(f"缓存需要刷新: {health['status']}")
    try:
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, "warmup_full.py"],
            capture_output=True, text=True, timeout=1800
        )
        logger.info(f"缓存刷新完成: {r.stdout[-200:]}")
        return True
    except Exception as e:
        logger.warning(f"缓存刷新失败: {e}")
        return False
