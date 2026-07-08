"""
数据服务 (Data Service)
======================
独立进程运行，负责：
1. 从多数据源采集行情
2. 计算技术指标
3. 写入共享缓存（data_cache/ + 信号总线通知）

其他模块不再直接调 data_prod/data_global，
而是从 data_cache/ 读 parquet 文件，或从总线拿通知。

设计原则：
- 独立进程，可随时启停
- 挂了不影响交易（策略用缓存数据继续跑）
- 每次更新完发一条 data_update 消息到总线
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [DATA] %(message)s")
logger = logging.getLogger("quant.data_service")

# 确保能找到项目根目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 引入信号总线（通知其他模块数据已更新）
import signal_bus

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ============================================================
# 数据采集
# ============================================================

def fetch_all_tickers() -> list[str]:
    """获取全市场股票列表（从 data_global 或配置）"""
    try:
        from data_global import get_us_tickers
        tickers = get_us_tickers(min_price=3.0, max_count=600)
        if tickers:
            logger.info(f"  获取到 {len(tickers)} 只美股")
            return tickers
    except Exception as e:
        logger.warning(f"  get_us_tickers 失败: {e}")

    # 回退到 data_prod 的固定列表
    try:
        from data_prod import get_tickers
        tickers = get_tickers()
        logger.info(f"  回退固定列表: {len(tickers)} 只")
        return tickers
    except Exception as e:
        logger.error(f"  获取股票列表全部失败: {e}")
        return []


def update_prices(tickers: list[str] = None, days_back: int = 10):
    """
    增量更新行情数据
    - 从 data_prod 拉取最新 K 线
    - 计算技术指标
    - 写入 data_cache/
    """
    from data_prod import fetch_prices, compute_indicators, load_price_cache, save_price_cache

    if tickers is None:
        tickers = fetch_all_tickers()

    # 分批获取，每次50只，避免被限流
    batch_size = 50
    total = len(tickers)
    updated_count = 0

    for i in range(0, total, batch_size):
        batch = tickers[i:i + batch_size]
        try:
            prices = fetch_prices(batch)
            if prices:
                # 计算指标
                for tkr, df in prices.items():
                    if df is not None and len(df) > 20:
                        prices[tkr] = compute_indicators(df)

                # 写入缓存
                existing = load_price_cache()
                existing.update(prices)
                save_price_cache(existing)

                updated_count += len(prices)
                logger.info(f"  [{i}/{total}] 更新 {len(prices)} 只, 共 {updated_count} 只")
        except Exception as e:
            logger.warning(f"  [{i}/{total}] 批次失败: {e}")
            time.sleep(2)
            continue

        # 避免请求过快
        time.sleep(0.5)

    logger.info(f"  更新完成: {updated_count} 只")
    return updated_count


def update_spy():
    """更新 SPY 基准数据"""
    try:
        from spy_source import fetch_spy
        spy = fetch_spy()
        if spy is not None:
            from data_prod import compute_indicators
            spy = compute_indicators(spy)
            # 保存到特定位置
            spy_path = os.path.join(CACHE_DIR, "spy.pkl")
            import pickle
            with open(spy_path, "wb") as f:
                pickle.dump(spy, f)
            logger.info(f"  SPY 更新完成: {len(spy)} 行")
            return True
    except Exception as e:
        logger.warning(f"  SPY 更新失败: {e}")
    return False


# ============================================================
# 完整更新流程
# ============================================================

def run_update(full: bool = False):
    """执行一次完整数据更新"""
    t0 = datetime.now()
    logger.info("=" * 45)
    logger.info("  📡 数据服务 - 开始更新")
    logger.info("=" * 45)

    # 1. 获取股票列表
    tickers = fetch_all_tickers()
    if not tickers:
        logger.error("无股票列表，退出")
        return False

    # 2. 更新行情
    days = 30 if full else 10
    count = update_prices(tickers, days_back=days)

    # 3. 更新 SPY
    update_spy()

    # 4. 发总线通知
    elapsed = (datetime.now() - t0).total_seconds()
    signal_bus.write_message("data_service", "data_update", {
        "tickers_count": len(tickers),
        "updated_count": count,
        "full_update": full,
        "elapsed_seconds": round(elapsed, 1),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    logger.info(f"  完成: {count} 只, 耗时 {elapsed:.1f}s")
    return True


# ============================================================
# 健康检查
# ============================================================

def check_health() -> dict:
    """数据服务健康检查"""
    from cache_manager import check_cache_health
    health = check_cache_health()

    # 检查缓存年龄
    cache_path = os.path.join(CACHE_DIR, "prices.pkl")
    cache_age = None
    cache_size = 0
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        cache_age = (time.time() - mtime) / 3600  # 小时
        cache_size = os.path.getsize(cache_path)

    return {
        "status": "healthy" if cache_age is not None and cache_age < 48 else "stale",
        "cache_age_hours": round(cache_age, 1) if cache_age else None,
        "cache_size_mb": round(cache_size / 1024 / 1024, 1) if cache_size else 0,
        "needs_refresh": health.get("needs_refresh", True),
        "stocks_count": health.get("stock_count", 0),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ============================================================
# 后台循环
# ============================================================

def run_loop(interval_minutes: int = 60):
    """
    持续运行模式
    - 每60分钟增量更新
    - 每天一次全量更新（美东收盘后）
    """
    logger.info(f"🚀 数据服务启动, 更新间隔={interval_minutes}分钟")

    last_full = None

    while True:
        now = datetime.now()

        # 判断是否全量更新（每天美东17:00后第一次运行）
        is_full = False
        if last_full is None or (now - last_full).total_seconds() > 20 * 3600:
            # 北京时间 05:00 = 美东 17:00（收盘后）
            if now.hour >= 5 or now.hour < 9:
                is_full = True

        try:
            run_update(full=is_full)
            if is_full:
                last_full = now
        except Exception as e:
            logger.error(f"更新异常: {e}")

        time.sleep(interval_minutes * 60)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数据服务")
    parser.add_argument("--once", action="store_true", help="只更新一次")
    parser.add_argument("--full", action="store_true", help="全量更新（30天数据）")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔(分钟)")
    parser.add_argument("--health", action="store_true", help="健康检查")
    parser.add_argument("--loop", action="store_true", help="持续运行")
    args = parser.parse_args()

    if args.health:
        h = check_health()
        print(f"📡 数据服务状态")
        print(f"  状态: {h['status']}")
        print(f"  缓存: {h['cache_age_hours']}小时前更新 ({h['cache_size_mb']}MB)")
        print(f"  股票数: {h['stocks_count']}")
        print(f"  需要刷新: {h['needs_refresh']}")

    elif args.once:
        run_update(full=args.full)

    elif args.loop:
        run_loop(interval_minutes=args.interval)

    else:
        run_update(full=args.full)
