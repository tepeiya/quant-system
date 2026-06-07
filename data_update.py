"""
增量数据更新工具
==============
用法：python3 data_update.py
功能：增量更新缓存，只补最近交易日数据，不重下全部历史
"""
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("quant.update")


def update():
    """增量更新所有缓存股票的最新数据"""
    from data_prod import refresh_cache
    result = refresh_cache(days_back=10)
    total = sum(result.values()) if result else 0
    logger.info(f"更新完成: {len(result)}只, 共{total}行新数据")
    return len(result)


if __name__ == "__main__":
    update()
