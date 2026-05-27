"""
数据补全脚本 - 慢速稳定模式
=========================
目标：把S&P 500数据从80只补到500只。
策略：
  1. 优先Tiingo（限流慢速，每分钟5只）
  2. 如果Tiingo被限流，等60秒再继续
  3. 已有缓存的不重复获取
  4. 每50只保存一次

运行：cd /var/minis/workspace/quant_system && . ./env_setup.sh && python3 data_filler.py
"""

import logging, os, sys, time, json
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("quant.filler")

from data_prod import _fetch_tiingo, load_price_cache, save_price_cache, compute_indicators, get_tickers


def fill_batch(batch: list, start_date="2018-01-01", end_date="2026-05-24") -> int:
    """补一批数据，返回成功数"""
    cache = load_price_cache()
    taken = 0
    for i, t in enumerate(batch):
        if t in cache:
            continue
        df = _fetch_tiingo(t, start_date, end_date)
        if df is not None and len(df) >= 200:
            cache[t] = compute_indicators(df)
            taken += 1
            if taken % 10 == 0:
                logger.info(f"  {t}: {len(df)}行 ({taken}/{len(batch)})")
        else:
            logger.warning(f"  {t}: 跳过")
        time.sleep(2.5)  # 每分钟约24只

        # 每20只保存+休息
        if taken > 0 and taken % 20 == 0:
            save_price_cache(cache)
            logger.info(f"  保存{len(cache)}只")
            time.sleep(5)

    save_price_cache(cache)
    return taken


def check_remaining() -> tuple:
    """查看还差多少"""
    cache = load_price_cache()
    all_t = set(get_tickers())
    cached = set(cache.keys())
    missing = sorted(all_t - cached)
    return len(cache), len(missing), missing


def fill_all():
    """分批次补全"""
    total, remaining, missing = check_remaining()
    logger.info(f"当前: {total}只, 还需: {len(missing)}只")

    if not missing:
        logger.info("🎉 已全量完成！")
        return

    # 生成排除列表：已知Tiingo不支持的含特殊字符的ticker
    special = {t for t in missing if '.' in t or '-' in t or '/' in t}
    if special:
        logger.info(f"跳过特殊字符ticker: {len(special)}只")
        missing = [t for t in missing if t not in special]

    # 分批次
    BATCH_SIZE = 100
    for batch_idx in range(0, len(missing), BATCH_SIZE):
        batch = missing[batch_idx:batch_idx + BATCH_SIZE]
        logger.info(f"\n批次 {batch_idx//BATCH_SIZE + 1}/{(len(missing)-1)//BATCH_SIZE + 1}: {len(batch)}只")
        taken = fill_batch(batch)

        total, remaining, _ = check_remaining()
        logger.info(f"当前: {total}只, 剩余: {len(remaining)}只")

        if remaining == 0:
            break

        # 批次间大休息
        if batch_idx + BATCH_SIZE < len(missing):
            wait = 20 if taken < len(batch) * 0.3 else 10
            logger.info(f"批次间休息{wait}秒...")
            time.sleep(wait)

    total, remaining, _ = check_remaining()
    logger.info(f"\n{'='*50}")
    logger.info(f"完成: {total}只, 剩余: {remaining}只")
    if remaining > 0:
        logger.info(f"剩余ticker: {remaining}")
        # 存一个列表方便继续
        with open("data_cache/remaining_tickers.json", "w") as f:
            json.dump(missing[len(missing)-remaining:], f, indent=2)
        logger.info("剩余列表已保存到 data_cache/remaining_tickers.json")


if __name__ == "__main__":
    fill_all()
