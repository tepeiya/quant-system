"""
止损监控服务 v2 - ATR动态止损
===========================
功能：每5分钟检查持仓
  1. 静态止损：亏损 > stop_loss_pct%
  2. ATR动态止损：亏损 > ATR × stop_loss_atr_multiple
  3. 跟踪止损：浮盈超过trailing_activate_pct后，从最高点回落 N倍ATR

启动：python3 stop_loss_monitor.py
"""

import os
import logging
import time
from datetime import datetime

from system_config import get as get_cfg

logger = logging.getLogger("quant.stop_loss")

# 止损参数
STOP_LOSS_STATIC = get_cfg("stop_loss_pct", 15)
ATR_MULTIPLE = get_cfg("stop_loss_atr_multiple", 3.0)
STOP_LOSS_MIN = get_cfg("stop_loss_min_pct", 5)
STOP_LOSS_MAX = get_cfg("stop_loss_max_pct", 25)
TRAILING_ACTIVATE = get_cfg("trailing_stop_activate_pct", 15)
TRAILING_ATR = get_cfg("trailing_stop_atr_multiple", 2.0)
TRAILING_MIN = get_cfg("trailing_stop_min_pct", 8)


def get_atr(symbol: str) -> float:
    """从本地缓存读取股票的ATR值"""
    try:
        from data_prod import load_price_cache
        cache = load_price_cache()
        df = cache.get(symbol)
        if df is not None and "ATR_Pct" in df.columns:
            atr = df["ATR_Pct"].iloc[-1]
            return float(atr) if not pd.isna(atr) else 3.0
    except:
        pass
    return 3.0  # 默认


def get_recent_high(symbol: str, days=60) -> float:
    """过去60天最高价"""
    try:
        from data_prod import load_price_cache
        cache = load_price_cache()
        df = cache.get(symbol)
        if df is not None and len(df) > days:
            return float(df["High"].iloc[-days:].max())
    except:
        pass
    return 0


def check_and_stop():
    """检查持仓，ATR动态止损"""
    import requests
    import numpy as np
    import pandas as pd
    from data_prod import load_price_cache
    
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        return None

    base = "https://paper-api.alpaca.markets"
    auth = (KEY, SECRET)

    try:
        r = requests.get(f"{base}/v2/positions", auth=auth, timeout=10)
        if r.status_code != 200:
            return None
        positions = r.json()
    except:
        return None

    # 加载ATR数据
    cache = load_price_cache()

    stopped = []
    for p in positions:
        sym = p["symbol"]
        qty = int(p["qty"])
        cost = float(p.get("cost_basis", 0))
        mv = float(p["market_value"])
        cur_price = float(p["current_price"])
        if cost <= 0:
            continue
        pnl_pct = (mv - cost) / max(cost, 1) * 100

        # ATR动态止损
        df = cache.get(sym)
        atr = 3.0
        if df is not None and "ATR_Pct" in df.columns:
            try:
                atr = float(df["ATR_Pct"].iloc[-1])
            except:
                pass
        atr_stop = max(STOP_LOSS_MIN, min(STOP_LOSS_MAX, atr * ATR_MULTIPLE))

        # 跟踪止损
        avg_entry = float(p.get("avg_entry_price", 0))
        trailing_triggered = False
        if avg_entry > 0:
            pnl_from_entry = (cur_price / avg_entry - 1) * 100
            if pnl_from_entry > TRAILING_ACTIVATE:
                # 从最高点回落
                peak = get_recent_high(sym)
                if peak > avg_entry:
                    trailing_dist = max(TRAILING_MIN, atr * TRAILING_ATR)
                    if cur_price < peak * (1 - trailing_dist / 100):
                        trailing_triggered = True

        # 判断是否需要止损
        should_stop = pnl_pct < -STOP_LOSS_STATIC or pnl_pct < -atr_stop or trailing_triggered

        if should_stop:
            reason = "跟踪止损" if trailing_triggered else f"静态{STOP_LOSS_STATIC}%/ATR{atr_stop:.0f}%"
            logger.warning(f"⚠️ 止损触发: {sym} PnL={pnl_pct:+.1f}% ({reason})")
            try:
                r2 = requests.delete(f"{base}/v2/positions/{sym}", auth=auth, timeout=10)
                if r2.status_code == 200:
                    logger.info(f"✅ 止损平仓: {sym} x{qty}")
                    stopped.append({
                        "symbol": sym, "pnl_pct": round(pnl_pct, 2),
                        "reason": reason, "time": str(datetime.now())
                    })
            except Exception as e:
                logger.error(f"❌ 止损失败 {sym}: {e}")

    return stopped


def run_monitor(interval=300):
    """后台运行监控"""
    logger.info(f"止损监控启动(ATR动态), 间隔{interval}s")
    while True:
        try:
            check_and_stop()
        except Exception as e:
            logger.error(f"监控异常: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    result = check_and_stop()
    if result:
        for s in result:
            print(f"⚠️ 已止损: {s['symbol']} ({s['reason']})")
    else:
        print("✅ 一切正常，无需止损")

    from risk_alerts import check_alerts, push_alerts
    alerts = check_alerts()
    if alerts:
        print(f"⚠️ 告警 {len(alerts)} 条")
        push_alerts(alerts)
    else:
        print("✅ 无告警")
