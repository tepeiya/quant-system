"""
全局时区配置
所有模块统一通过此模块获取时间和处理时区
"""
from datetime import datetime, timezone, timedelta
import pandas as pd

# 系统统一使用美东时间（ET）
# 夏令时 EDT = UTC-4, 冬令时 EST = UTC-5
# 这里统一用 UTC 存储，显示时转 ET
SYSTEM_TIMEZONE = "America/New_York"

# 缓存数据的默认时区（data_prod 保存时统一去掉时区）
CACHE_TZ = None  # data_cache 里存的是无时区的 UTC 时间


def now_utc() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


def now_et() -> datetime:
    """获取当前美东时间"""
    from pytz import timezone
    return datetime.now(timezone(SYSTEM_TIMEZONE))


def today_str() -> str:
    """获取今天日期字符串 YYYY-MM-DD"""
    return now_utc().strftime("%Y-%m-%d")


def today_et_str() -> str:
    """获取美东今天日期字符串"""
    return now_et().strftime("%Y-%m-%d")


def ensure_no_tz(series_or_index):
    """
    确保时间索引无时区（data_cache 统一格式）
    data_prod 保存时去掉时区，读取时也去掉时区
    """
    if hasattr(series_or_index, 'tz') and series_or_index.tz is not None:
        return series_or_index.tz_localize(None)
    return series_or_index


def align_ts(target_ts, index):
    """
    对齐目标时间到 index 的时区
    daily_signal 中用来匹配 df.index 的时区
    """
    import pandas as pd
    if isinstance(target_ts, str):
        target_ts = pd.Timestamp(target_ts)
    if hasattr(index, 'tz') and index.tz is not None:
        if target_ts.tz is None:
            target_ts = target_ts.tz_localize("UTC")
        target_ts = target_ts.tz_convert(index.tz)
    else:
        if target_ts.tz is not None:
            target_ts = target_ts.tz_localize(None)
    return target_ts


def fix_df_timezone(df: pd.DataFrame) -> pd.DataFrame:
    """
    修复 DataFrame 索引时区问题
    - 如果 index 有时区，去掉时区（统一为无时区 UTC）
    """
    if df is None or df.empty:
        return df
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df
