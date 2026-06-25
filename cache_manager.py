"""
缓存管理模块 v1.0
=================
提供多级缓存支持：Redis → 内存 → 文件

功能：
1. Redis分布式缓存
2. 本地内存缓存（LRU）
3. 自动降级（Redis不可用时使用本地缓存）
4. 缓存预热与失效机制
"""

import os
import json
import time
import hashlib
import logging
from typing import Any, Optional, Callable
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger("quant.cache")

# 配置
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

# 缓存配置
DEFAULT_TTL = 3600  # 默认1小时
PRICE_CACHE_TTL = 300  # 行情数据5分钟
SIGNAL_CACHE_TTL = 3600  # 信号1小时
CONFIG_CACHE_TTL = 86400  # 配置24小时

# 全局Redis连接
_redis_client = None
_local_cache = {}  # 本地内存缓存
_local_cache_expiry = {}  # 过期时间


def get_redis_client():
    """获取Redis客户端"""
    global _redis_client
    
    if _redis_client is not None:
        return _redis_client
    
    try:
        import redis
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        # 测试连接
        _redis_client.ping()
        logger.info(f"✅ Redis连接成功: {REDIS_HOST}:{REDIS_PORT}")
        return _redis_client
    except ImportError:
        logger.warning("⚠️ redis模块未安装，使用本地缓存")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Redis连接失败: {e}，使用本地缓存")
        _redis_client = None
        return None


def _make_key(prefix: str, key: str) -> str:
    """生成缓存键"""
    return f"quant:{prefix}:{key}"


def _hash_key(key: str) -> str:
    """对长键进行哈希"""
    if len(key) > 200:
        return hashlib.md5(key.encode()).hexdigest()
    return key


# ===== 本地内存缓存 =====

def local_get(key: str) -> Optional[Any]:
    """从本地缓存获取"""
    if key not in _local_cache:
        return None
    
    # 检查过期
    if key in _local_cache_expiry:
        if time.time() > _local_cache_expiry[key]:
            del _local_cache[key]
            del _local_cache_expiry[key]
            return None
    
    return _local_cache[key]


def local_set(key: str, value: Any, ttl: int = DEFAULT_TTL):
    """设置本地缓存"""
    _local_cache[key] = value
    _local_cache_expiry[key] = time.time() + ttl


def local_delete(key: str):
    """删除本地缓存"""
    if key in _local_cache:
        del _local_cache[key]
    if key in _local_cache_expiry:
        del _local_cache_expiry[key]


def local_clear(prefix: str = None):
    """清空本地缓存"""
    global _local_cache, _local_cache_expiry
    
    if prefix:
        # 只删除指定前缀的键
        keys_to_delete = [k for k in _local_cache.keys() if k.startswith(f"quant:{prefix}:")]
        for k in keys_to_delete:
            local_delete(k)
    else:
        _local_cache = {}
        _local_cache_expiry = {}


# ===== Redis缓存操作 =====

def redis_get(key: str) -> Optional[Any]:
    """从Redis获取"""
    client = get_redis_client()
    if not client:
        return None
    
    try:
        value = client.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        logger.warning(f"Redis GET失败 {key}: {e}")
        return None


def redis_set(key: str, value: Any, ttl: int = DEFAULT_TTL):
    """设置Redis缓存"""
    client = get_redis_client()
    if not client:
        return False
    
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
        return True
    except Exception as e:
        logger.warning(f"Redis SET失败 {key}: {e}")
        return False


def redis_delete(key: str):
    """删除Redis缓存"""
    client = get_redis_client()
    if not client:
        return False
    
    try:
        client.delete(key)
        return True
    except Exception as e:
        logger.warning(f"Redis DELETE失败 {key}: {e}")
        return False


def redis_exists(key: str) -> bool:
    """检查键是否存在"""
    client = get_redis_client()
    if not client:
        return False
    
    try:
        return client.exists(key) > 0
    except Exception:
        return False


def redis_clear(prefix: str = None):
    """清空Redis缓存"""
    client = get_redis_client()
    if not client:
        return False
    
    try:
        if prefix:
            pattern = f"quant:{prefix}:*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)
                logger.info(f"🗑️ 已清空 {len(keys)} 个缓存键: {pattern}")
        else:
            # 清空所有quant:开头的键
            keys = client.keys("quant:*")
            if keys:
                client.delete(*keys)
                logger.info(f"🗑️ 已清空 {len(keys)} 个缓存键")
        return True
    except Exception as e:
        logger.warning(f"Redis CLEAR失败: {e}")
        return False


# ===== 统一缓存接口 =====

def cache_get(prefix: str, key: str) -> Optional[Any]:
    """统一获取缓存（Redis优先，回退到本地）"""
    redis_key = _make_key(prefix, key)
    
    # 先尝试Redis
    value = redis_get(redis_key)
    if value is not None:
        return value
    
    # 回退到本地
    return local_get(redis_key)


def cache_set(prefix: str, key: str, value: Any, ttl: int = DEFAULT_TTL):
    """统一设置缓存（同时写入Redis和本地）"""
    redis_key = _make_key(prefix, key)
    
    # 同时写入Redis和本地
    redis_set(redis_key, value, ttl)
    local_set(redis_key, value, ttl)


def cache_delete(prefix: str, key: str):
    """统一删除缓存"""
    redis_key = _make_key(prefix, key)
    
    redis_delete(redis_key)
    local_delete(redis_key)


def cache_exists(prefix: str, key: str) -> bool:
    """检查缓存是否存在"""
    redis_key = _make_key(prefix, key)
    
    return redis_exists(redis_key) or local_get(redis_key) is not None


def cache_clear(prefix: str = None):
    """清空缓存"""
    redis_clear(prefix)
    local_clear(prefix)


# ===== 缓存装饰器 =====

def cached(prefix: str, ttl: int = DEFAULT_TTL, key_func: Callable = None):
    """
    缓存装饰器
    
    用法：
    @cached("test", ttl=300)
    def get_data(arg1, arg2):
        return expensive_operation(arg1, arg2)
    
    # 自定义缓存键
    @cached("test", key_func=lambda args, kwargs: f"{args[0]}_{args[1]}")
    def get_data(ticker, period):
        return fetch_data(ticker, period)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(args, kwargs)
            else:
                # 默认使用函数名+参数生成键
                cache_key = _hash_key(f"{func.__name__}:{str(args)}:{str(kwargs)}")
            
            redis_key = _make_key(prefix, cache_key)
            
            # 尝试从缓存获取
            value = cache_get(prefix, cache_key)
            if value is not None:
                logger.debug(f"📦 缓存命中: {redis_key}")
                return value
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 存入缓存
            if result is not None:
                cache_set(prefix, cache_key, result, ttl)
                logger.debug(f"💾 已缓存: {redis_key} (TTL={ttl}s)")
            
            return result
        return wrapper
    return decorator


# ===== 特定数据缓存 =====

class PriceCache:
    """行情数据缓存"""
    
    @staticmethod
    def get(ticker: str) -> Optional[dict]:
        """获取股票行情"""
        return cache_get("prices", ticker)
    
    @staticmethod
    def set(ticker: str, data: dict, ttl: int = PRICE_CACHE_TTL):
        """设置股票行情"""
        cache_set("prices", ticker, data, ttl)
    
    @staticmethod
    def delete(ticker: str):
        """删除股票行情"""
        cache_delete("prices", ticker)
    
    @staticmethod
    def clear():
        """清空行情缓存"""
        cache_clear("prices")
    
    @staticmethod
    def get_multi(tickers: list[str]) -> dict:
        """批量获取行情"""
        result = {}
        for ticker in tickers:
            data = PriceCache.get(ticker)
            if data:
                result[ticker] = data
        return result


class SignalCache:
    """信号数据缓存"""
    
    @staticmethod
    def get(strategy: str = "conservative") -> Optional[dict]:
        """获取策略信号"""
        return cache_get("signals", strategy)
    
    @staticmethod
    def set(strategy: str, data: dict, ttl: int = SIGNAL_CACHE_TTL):
        """设置策略信号"""
        cache_set("signals", strategy, data, ttl)
    
    @staticmethod
    def get_today() -> Optional[dict]:
        """获取今日信号"""
        today = datetime.now().strftime("%Y-%m-%d")
        return cache_get("signals", f"today_{today}")
    
    @staticmethod
    def set_today(data: dict, ttl: int = SIGNAL_CACHE_TTL):
        """设置今日信号"""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_set("signals", f"today_{today}", data, ttl)
    
    @staticmethod
    def clear():
        """清空信号缓存"""
        cache_clear("signals")


class ConfigCache:
    """配置缓存"""
    
    @staticmethod
    def get(key: str) -> Optional[Any]:
        """获取配置"""
        return cache_get("config", key)
    
    @staticmethod
    def set(key: str, value: Any, ttl: int = CONFIG_CACHE_TTL):
        """设置配置"""
        cache_set("config", key, value, ttl)
    
    @staticmethod
    def delete(key: str):
        """删除配置"""
        cache_delete("config", key)
    
    @staticmethod
    def clear():
        """清空配置缓存"""
        cache_clear("config")


# ===== 缓存预热 =====

def warmup_cache():
    """预热缓存 - 加载常用数据到缓存"""
    logger.info("🚀 开始缓存预热...")
    
    # 1. 预热配置文件
    try:
        from database import get_config
        config_keys = [
            "factor_weights", "system_config", "broker_config",
            "intraday_config", "factor_ranking"
        ]
        for key in config_keys:
            value = get_config(key)
            if value:
                ConfigCache.set(key, value)
        logger.info(f"  ✅ 配置缓存预热完成: {len(config_keys)} 项")
    except Exception as e:
        logger.warning(f"  ⚠️ 配置预热失败: {e}")
    
    # 2. 预热市场数据
    try:
        import requests
        # 预热SPY数据
        spy_url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
        response = requests.get(spy_url, timeout=5)
        if response.status_code == 200:
            PriceCache.set("SPY", response.json())
            logger.info("  ✅ 市场数据预热完成: SPY")
    except Exception as e:
        logger.warning(f"  ⚠️ 市场数据预热失败: {e}")
    
    # 3. 预热指数成分
    try:
        from data_global import get_us_tickers
        tickers = get_us_tickers(min_price=5.0, max_count=50)
        if tickers:
            cache_set("system", "top_tickers", tickers, ttl=3600)
            logger.info(f"  ✅ 指数成分预热完成: {len(tickers)} 只")
    except Exception as e:
        logger.warning(f"  ⚠️ 指数成分预热失败: {e}")
    
    logger.info("🎉 缓存预热完成")


# ===== 缓存统计 =====

def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    client = get_redis_client()
    
    stats = {
        "redis_available": client is not None,
        "local_cache_size": len(_local_cache),
        "redis_keys": 0,
        "memory_used": 0
    }
    
    if client:
        try:
            # 统计quant:开头的键数量
            keys = client.keys("quant:*")
            stats["redis_keys"] = len(keys)
            
            # 估算内存使用
            info = client.info("memory")
            stats["memory_used"] = info.get("used_memory_human", "N/A")
        except Exception as e:
            logger.warning(f"获取Redis统计失败: {e}")
    
    return stats


def print_cache_stats():
    """打印缓存统计"""
    stats = get_cache_stats()
    
    print("\n📊 缓存状态")
    print("=" * 50)
    print(f"  Redis: {'✅ 已连接' if stats['redis_available'] else '❌ 未连接'}")
    print(f"  Redis键数: {stats['redis_keys']}")
    print(f"  本地缓存: {stats['local_cache_size']} 条")
    print(f"  内存使用: {stats['memory_used']}")
    print("=" * 50)


# 导出
__all__ = [
    "cache_get", "cache_set", "cache_delete", "cache_exists", "cache_clear",
    "local_get", "local_set", "local_delete", "local_clear",
    "redis_get", "redis_set", "redis_delete", "redis_clear", "redis_exists",
    "cached",
    "PriceCache", "SignalCache", "ConfigCache",
    "warmup_cache", "get_cache_stats", "print_cache_stats",
    "DEFAULT_TTL", "PRICE_CACHE_TTL", "SIGNAL_CACHE_TTL", "CONFIG_CACHE_TTL"
]
