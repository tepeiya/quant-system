"""
信号总线 (Signal Bus)
=====================
统一消息格式 + SQLite 消息队列
各策略只负责"算信号、写总线"
执行器只负责"读总线、下单"
模块间完全解耦，互不影响
"""

import json
import os
import sqlite3
from datetime import datetime

BUS_DIR = os.path.dirname(os.path.abspath(__file__))
BUS_DB = os.path.join(BUS_DIR, "data", "signal_bus.db")

# ============================================================
# 统一信号消息格式
# ============================================================
#
# 所有策略写入总线的消息都遵循这个结构：
#
# {
#     "msg_id":           "uuid",          # 自动生成，唯一
#     "strategy":         "conservative",   # 策略标识: conservative / momentum / intraday / pairs / wheel
#     "msg_type":         "signal",         # 消息类型: signal / order / risk_event / data_update
#     "timestamp":        "2026-06-21 09:30:00",
#     "date":             "2026-06-21",
#     "market_hour":      "premarket",      # premarket / regular / afterhours / closed
#     "payload": { ... }                    # 不同msg_type有不同的payload结构
# }
#
# ---- signal 消息的 payload 格式 ----
# {
#     "market": {"spy": 5432, "rsi": 62, "trend": "多头", "action": "正常买入"},
#     "candidates": [
#         {"ticker": "AAPL", "score": 85.3, "price": 198.5, ...},
#         ...
#     ],
#     "buy_list": ["AAPL", "MSFT", ...],       # 建议买入列表
#     "sell_list": [...],                       # 建议卖出列表
#     "hold_list": [...],                       # 建议持有列表
#     "metadata": {"signal_file": "...", "quality_used": true}
# }
#
# ---- order 消息的 payload 格式 ----
# {
#     "ticker": "AAPL",
#     "side": "buy" / "sell",
#     "qty": 100,
#     "price": 198.5,
#     "order_type": "market" / "limit" / "stop",
#     "reason": "signal" / "stop_loss" / "take_profit" / "trailing_stop" / "manual",
#     "source_strategy": "conservative",
# }
#
# ---- risk_event 消息的 payload 格式 ----
# {
#     "event_type": "drawdown_alert" / "circuit_break" / "stop_loss" / "hedge_trigger",
#     "severity": "info" / "warning" / "critical",
#     "message": "...",
#     "data": { ... }
# }


# ============================================================
# 数据库初始化
# ============================================================

def init_db():
    """创建消息总线表"""
    os.makedirs(os.path.dirname(BUS_DB), exist_ok=True)
    try:
        conn = sqlite3.connect(BUS_DB)
        c = conn.cursor()
    except sqlite3.DatabaseError:
        # 数据库文件损坏，删除并重建
        import shutil
        backup = BUS_DB + ".corrupted"
        try:
            shutil.move(BUS_DB, backup)
        except:
            pass
        try:
            os.remove(BUS_DB)
        except:
            pass
        conn = sqlite3.connect(BUS_DB)
        c = conn.cursor()

    # 消息队列 — 各策略写入信号，执行器读取消费
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id TEXT UNIQUE NOT NULL,
            strategy TEXT NOT NULL,
            msg_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT
        )
    """)

    # 策略心跳 — 记录各策略运行状态
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_heartbeat (
            strategy TEXT PRIMARY KEY,
            last_run TEXT,
            status TEXT DEFAULT 'idle',
            last_error TEXT,
            message_count INTEGER DEFAULT 0
        )
    """)

    # 消费偏移量 — 执行器记录已处理到哪条消息
    c.execute("""
        CREATE TABLE IF NOT EXISTS consumer_offsets (
            consumer TEXT PRIMARY KEY,
            last_msg_id INTEGER,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# 写消息 (策略 → 总线)
# ============================================================

def _gen_msg_id():
    import uuid
    return str(uuid.uuid4())[:8]


def write_message(strategy: str, msg_type: str, payload: dict, date: str = None) -> dict:
    """
    策略调用此函数写入消息到总线
    返回消息ID
    """
    import uuid
    now = datetime.now()
    msg_id = str(uuid.uuid4())[:12]
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    dt = date or now.strftime("%Y-%m-%d")

    # 判断交易时段
    h = now.hour + now.minute / 60
    # 美东夏令时 = UTC-4, 北京=UTC+8 → 时差12小时
    # 美东9:30-16:00 = 北京时间21:30-04:00
    et_h = (h - 12) % 24  # 粗略转美东
    if 9.5 <= et_h < 16:
        market_hour = "regular"
    elif 4 <= et_h < 9.5:
        market_hour = "premarket"
    elif 16 <= et_h < 20:
        market_hour = "afterhours"
    else:
        market_hour = "closed"

    msg = {
        "msg_id": msg_id,
        "strategy": strategy,
        "msg_type": msg_type,
        "timestamp": ts,
        "date": dt,
        "market_hour": market_hour,
        "payload": payload,
    }

    conn = sqlite3.connect(BUS_DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (msg_id, strategy, msg_type, timestamp, date, payload, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (msg_id, strategy, msg_type, ts, dt, json.dumps(payload, ensure_ascii=False, default=str), ts)
    )
    # 更新心跳
    c.execute(
        "INSERT INTO strategy_heartbeat (strategy, last_run, status, message_count) "
        "VALUES (?,?,?,'1') ON CONFLICT(strategy) DO UPDATE SET "
        "last_run=excluded.last_run, status='ok', message_count=CAST(message_count AS INTEGER)+1",
        (strategy, ts, 'ok')
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "msg_id": msg_id, "message": f"{strategy} 写入 {msg_type} 消息"}


# ============================================================
# 读消息 (总线 → 执行器)
# ============================================================

def read_pending_messages(consumer: str = "executor", limit: int = 20) -> list[dict]:
    """
    执行器调用此函数读取待处理消息
    - 按消息ID顺序消费
    - 记录消费偏移量，避免重复处理
    """
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 获取上次消费位置
    c.execute("SELECT last_msg_id FROM consumer_offsets WHERE consumer=?", (consumer,))
    row = c.fetchone()
    last_id = row["last_msg_id"] if row else 0

    # 读取新消息（只取 status='pending' 的）
    c.execute(
        "SELECT * FROM messages WHERE id > ? AND status='pending' ORDER BY id ASC LIMIT ?",
        (last_id, limit)
    )
    rows = c.fetchall()

    # 更新消费偏移量 + 标记消息为 processing（防止重复消费）
    if rows:
        max_id = rows[-1]["id"]
        c.execute(
            "INSERT INTO consumer_offsets (consumer, last_msg_id, updated_at) "
            "VALUES (?,?,?) ON CONFLICT(consumer) DO UPDATE SET "
            "last_msg_id=excluded.last_msg_id, updated_at=excluded.updated_at",
            (consumer, max_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        # 将读取的消息标记为 processing，避免重复消费
        msg_ids = [r["msg_id"] for r in rows]
        placeholders = ",".join("?" * len(msg_ids))
        c.execute(
            f"UPDATE messages SET status='processing' WHERE msg_id IN ({placeholders})",
            tuple(msg_ids)
        )

    conn.commit()
    conn.close()

    messages = []
    for row in rows:
        msg = dict(row)
        msg["payload"] = json.loads(msg["payload"])
        messages.append(msg)

    return messages


def mark_consumed(msg_id: str):
    """标记消息为已消费（执行器处理完毕后调用）"""
    conn = sqlite3.connect(BUS_DB)
    c = conn.cursor()
    c.execute(
        "UPDATE messages SET status='consumed', consumed_at=? WHERE msg_id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg_id)
    )
    conn.commit()
    conn.close()


def mark_failed(msg_id: str, error: str):
    """标记消息为处理失败"""
    conn = sqlite3.connect(BUS_DB)
    c = conn.cursor()
    c.execute(
        "UPDATE messages SET status='failed', consumed_at=? WHERE msg_id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg_id)
    )
    conn.commit()
    conn.close()


# ============================================================
# 辅助接口
# ============================================================

def get_pending_count() -> int:
    """获取待处理消息数"""
    conn = sqlite3.connect(BUS_DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE status='pending'")
    count = c.fetchone()[0]
    conn.close()
    return count


def get_strategy_heartbeats() -> list[dict]:
    """获取所有策略心跳状态"""
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM strategy_heartbeat ORDER BY strategy")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_consumers() -> list[dict]:
    """获取所有消费者状态"""
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM consumer_offsets ORDER BY consumer")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_messages(limit: int = 20) -> list[dict]:
    """获取最近消息"""
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    messages = []
    for row in rows:
        msg = dict(row)
        try:
            msg["payload"] = json.loads(msg["payload"])
        except:
            pass
        messages.append(msg)
    return messages


# ============================================================
# 快捷辅助：为现有策略提供适配器
# ============================================================

def write_signal(strategy: str, candidates: list[dict],
                 market: dict = None, buy_list: list = None,
                 sell_list: list = None, hold_list: list = None,
                 metadata: dict = None) -> dict:
    """快捷写入 signal 类型消息"""
    payload = {
        "candidates": candidates,
        "buy_list": buy_list or [],
        "sell_list": sell_list or [],
        "hold_list": hold_list or [],
        "metadata": metadata or {},
    }
    if market:
        payload["market"] = market
    return write_message(strategy, "signal", payload)


def write_order(ticker: str, side: str, qty: int, price: float,
                order_type: str = "market", reason: str = "signal",
                source_strategy: str = "unknown",
                order_id: str = None, filled_qty: int = None) -> dict:
    """快捷写入 order 类型消息"""
    payload = {
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": price,
        "order_type": order_type,
        "reason": reason,
        "source_strategy": source_strategy,
    }
    if order_id:
        payload["order_id"] = order_id
    if filled_qty is not None:
        payload["filled_qty"] = filled_qty
    return write_message(source_strategy, "order", payload)


def write_risk_event(event_type: str, severity: str, message: str, data: dict = None) -> dict:
    """快捷写入 risk_event 类型消息"""
    payload = {
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "data": data or {},
    }
    return write_message("risk_service", "risk_event", payload)


# ============================================================
# 总线状态看板数据
# ============================================================

def get_bus_status() -> dict:
    """获取总线整体状态（供Web面板显示）"""
    return {
        "pending": get_pending_count(),
        "strategies": get_strategy_heartbeats(),
        "consumers": get_consumers(),
        "recent": get_recent_messages(5),
    }


# ============================================================
# 初始化
# ============================================================

init_db()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("📨 信号总线 - 管理工具")
        print(f"   数据库: {BUS_DB}")
        print("")
        print("   status         查看总线状态")
        print("   messages       查看最近消息")
        print("   strategies     查看策略心跳")
        print("   consumers      查看消费者")
        print("   clean          清理已消费消息")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        s = get_bus_status()
        print(f"📨 信号总线状态")
        print(f"   待处理: {s['pending']} 条")
        print(f"   策略: {len(s['strategies'])} 个")
        for st in s["strategies"]:
            print(f"     {st['strategy']}: {st['status']} (消息{st['message_count']}条)")
        print(f"   消费者: {len(s['consumers'])} 个")
        for c in s["consumers"]:
            print(f"     {c['consumer']}: 已读到 #{c['last_msg_id']}")
        if s["recent"]:
            print(f"   最近消息:")
            for m in s["recent"][:5]:
                print(f"     #{m['id']} [{m['strategy']}] {m['msg_type']} → {m['status']}")

    elif cmd == "messages":
        msgs = get_recent_messages(20)
        for m in msgs:
            print(f"  #{m['id']} {m['timestamp']} [{m['strategy']}] {m['msg_type']} {m['status']}")
            if isinstance(m["payload"], dict):
                p = m["payload"]
                if "candidates" in p:
                    print(f"      候选: {len(p['candidates'])}只")
                if "ticker" in p:
                    print(f"      标的: {p['ticker']} {p.get('side','')} {p.get('qty','')}股")

    elif cmd == "strategies":
        for s in get_strategy_heartbeats():
            print(f"  {s['strategy']}: {s['status']} (上次: {s.get('last_run','-')})")

    elif cmd == "consumers":
        for c in get_consumers():
            print(f"  {c['consumer']}: 消息 #{c['last_msg_id']} (更新: {c.get('updated_at','-')})")

    elif cmd == "clean":
        conn = sqlite3.connect(BUS_DB)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE status='consumed' AND datetime(consumed_at) < datetime('now', '-7 days')")
        deleted = c.rowcount
        conn.commit()
        conn.close()
        print(f"✅ 已清理 {deleted} 条旧消息")
