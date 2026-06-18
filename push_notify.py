"""
PushPlus 微信推送 — 信号通知/风控告警
=====================================
用法：
  from push_notify import send_signal_notify, send_alert
  
  send_signal_notify("AAPL", 85.3, 745.2, "🟢")
  send_alert("风控告警", "持仓MRVL跌幅超过12%")
"""

import os, json, logging
from datetime import datetime

logger = logging.getLogger("quant.notify")

CACHE_FILE = "data_cache/notify_cache.json"

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")


def _send(title: str, content: str, topic: str = "") -> bool:
    """发送 PushPlus 微信推送"""
    if not PUSHPLUS_TOKEN:
        return False

    try:
        import requests
        data = {
            "token": PUSHPLUS_TOKEN,
            "title": title[:100],
            "content": content,
            "template": "markdown",
        }
        if topic:
            data["topic"] = topic
        r = requests.post("https://www.pushplus.plus/send", json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"PushPlus 发送失败: {e}")
        return False


def _check_cooldown(key: str, minutes: int = 30) -> bool:
    """检查冷却时间，避免重复推送"""
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
        except:
            pass

    last = cache.get(key)
    if last:
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        if elapsed < minutes * 60:
            return False

    cache[key] = datetime.now().isoformat()
    try:
        os.makedirs("data_cache", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except:
        pass
    return True


def send_signal_notify(ticker: str, score: float, spy_price: float, trend: str):
    """信号生成通知"""
    key = f"signal_{datetime.now().strftime('%Y-%m-%d')}"
    if not _check_cooldown(key, minutes=60):
        return

    content = f"""## 📊 今日信号生成

**时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**大盘趋势：** {trend}
**SPY：** ${spy_price:.2f}

**今日 Top5：**
"""
    _send("📊 M+ 量化信号", content)


def send_trade_notify(action: str, symbol: str, qty: int, price: float, strategy: str):
    """交易执行通知"""
    key = f"trade_{symbol}_{datetime.now().strftime('%H')}"
    if not _check_cooldown(key, minutes=15):
        return

    icon = "🟢" if action == "BUY" else "🔴"
    content = f"""## {icon} 策略执行

**策略：** {strategy}
**操作：** {action} {symbol} x{qty}
**价格：** ${price:.2f}
**时间：** {datetime.now().strftime('%H:%M')}
"""
    _send(f"{icon} M+ 交易执行", content)


def send_alert(title: str, message: str):
    """风控告警推送"""
    key = f"alert_{title[:20]}"
    if not _check_cooldown(key, minutes=30):
        return

    content = f"""## ⚠️ 风控告警

**{title}**

{message}

**时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    _send(f"⚠️ M+ {title}", content)


def send_daily_summary(equity: float, pnl: float, positions: int, signal_count: int):
    """每日收盘总结"""
    now = datetime.now()
    key = f"daily_{now.strftime('%Y-%m-%d')}"
    if not _check_cooldown(key, minutes=120):
        return

    pnl_icon = "🟢" if pnl >= 0 else "🔴"
    content = f"""## 📈 M+ 每日总结

**日期：** {now.strftime('%Y-%m-%d')}
**总权益：** ${equity:.2f}
**当日盈亏：** {pnl_icon} ${pnl:+.2f}
**持仓：** {positions} 只
**信号：** {signal_count} 只候选

---
*自动推送 · 量化系统 M+*
"""
    _send("📈 M+ 每日总结", content)
