import logging
from datetime import datetime, timedelta

from data_prod import get_tickers, fetch_prices, save_price_cache, load_price_cache

logger = logging.getLogger("quant.warmup")


def warmup(batch_size=60):
    cache = load_price_cache()
    all_t = get_tickers()
    missing = [t for t in all_t if t not in cache or cache[t] is None or len(cache[t]) < 200]
    if not missing:
        logger.info("warmup: 无缺失数据")
        return {"ok": True, "fetched": 0, "remaining": 0}

    batch = missing[:batch_size]
    start = (datetime.now() - timedelta(days=365*6)).strftime("%Y-%m-%d")
    fetched = fetch_prices(batch, start=start, use_alpaca=True)
    save_price_cache(fetched)

    new_cache = load_price_cache()
    remaining = len([t for t in all_t if t not in new_cache or new_cache[t] is None or len(new_cache[t]) < 200])
    logger.info(f"warmup: 本轮{len(batch)}只, 剩余{remaining}只")
    return {"ok": True, "fetched": len(batch), "remaining": remaining}


if __name__ == "__main__":
    print(warmup())
