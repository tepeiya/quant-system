"""
订单管理器 v2 — 接入信号总线
============================
所有订单统一通过此模块记录 + 总线通知
"""
import os, json, time, logging
from datetime import datetime

logger = logging.getLogger('quant.order')

ORDERS_FILE = 'signals/orders_state.json'
TRADE_LOG_DIR = 'signals'

STATUS_NEW = 'NEW'
STATUS_SUBMITTED = 'SUBMITTED'
STATUS_PARTIAL = 'PARTIAL'
STATUS_FILLED = 'FILLED'
STATUS_REJECTED = 'REJECTED'
STATUS_CANCELED = 'CANCELED'
STATUS_DRY_RUN = 'DRY_RUN'


# ============================================================
# 内部存储
# ============================================================

def _load():
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE) as f:
                return json.load(f)
        except:
            return []
    return []


def _save(rows):
    os.makedirs('signals', exist_ok=True)
    with open(ORDERS_FILE, 'w') as f:
        json.dump(rows[-500:], f, indent=2, ensure_ascii=False)


# ============================================================
# 核心接口
# ============================================================

def new_intent(symbol, side, qty, broker='alpaca', strategy='unknown',
               price=0, reason='signal', order_type='market') -> dict:
    """创建新的交易意图，同时写入信号总线"""
    rows = _load()
    oid = f"{int(time.time()*1000)}_{symbol}_{side}"
    row = {
        'intent_id': oid, 'symbol': symbol, 'side': side, 'qty': qty,
        'price': price, 'broker': broker, 'strategy': strategy,
        'order_type': order_type, 'reason': reason,
        'status': STATUS_NEW, 'created_at': str(datetime.now()),
        'retry_count': 0, 'last_error': None,
    }
    rows.append(row)
    _save(rows)

    # 写到信号总线
    try:
        import signal_bus
        signal_bus.write_order(
            ticker=symbol, side=side, qty=qty, price=price,
            reason=reason, source_strategy=strategy,
        )
    except Exception:
        pass

    return row


def mark(intent_id, status, **kwargs):
    """更新订单状态"""
    rows = _load()
    for r in rows:
        if r.get('intent_id') == intent_id:
            r['status'] = status
            r.update(kwargs)
            r['updated_at'] = str(datetime.now())
            break
    _save(rows)


def mark_submitted(intent_id, broker_order_id=None):
    mark(intent_id, STATUS_SUBMITTED, broker_order_id=broker_order_id)


def mark_filled(intent_id, filled_qty=None, avg_price=None):
    mark(intent_id, STATUS_FILLED, filled_qty=filled_qty, avg_fill_price=avg_price)


def mark_partial(intent_id, filled_qty=None, avg_price=None):
    mark(intent_id, STATUS_PARTIAL, filled_qty=filled_qty, avg_fill_price=avg_price)


def mark_rejected(intent_id, error_msg=None):
    mark(intent_id, STATUS_REJECTED, last_error=error_msg)


def mark_dry_run(intent_id):
    mark(intent_id, STATUS_DRY_RUN)


# ============================================================
# 查询
# ============================================================

def get_orders(strategy=None, status=None, limit=50) -> list[dict]:
    """获取订单列表"""
    rows = _load()
    if strategy:
        rows = [r for r in rows if r.get('strategy') == strategy]
    if status:
        rows = [r for r in rows if r.get('status') == status]
    return rows[-limit:][::-1]


def get_today_orders() -> list[dict]:
    """获取今日订单"""
    today = datetime.now().strftime('%Y-%m-%d')
    rows = _load()
    return [r for r in rows if r.get('created_at', '').startswith(today)]


def get_stats() -> dict:
    """获取订单统计"""
    rows = _load()
    total = len(rows)
    by_status = {}
    by_strategy = {}
    for r in rows:
        s = r.get('status', 'UNKNOWN')
        by_status[s] = by_status.get(s, 0) + 1
        st = r.get('strategy', 'unknown')
        by_strategy[st] = by_strategy.get(st, 0) + 1
    return {
        'total': total,
        'by_status': by_status,
        'by_strategy': by_strategy,
        'today': len(get_today_orders()),
    }


# ============================================================
# 从旧版本迁移数据
# ============================================================

def migrate_from_old_logs():
    """从 paper_trader / paper_trader_momentum / intraday_trader 的旧日志导入"""
    import glob
    migrated = 0
    for pattern in ['signals/trade_log*.json', 'signals/intraday_trades*.json']:
        for f in glob.glob(pattern):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                trades = data.get('trades', data) if isinstance(data, dict) else data
                if isinstance(trades, list):
                    for t in trades:
                        if isinstance(t, dict) and 'intent_id' not in t:
                            symbol = t.get('symbol', t.get('ticker', ''))
                            side = t.get('side', 'buy')
                            qty = t.get('qty', 0)
                            if symbol and qty > 0:
                                new_intent(symbol, side, qty,
                                           reason=t.get('reason', 'migrated'))
                                migrated += 1
            except:
                pass
    logger.info(f"从旧日志迁移 {migrated} 条订单")
    return migrated


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'migrate':
        migrate_from_old_logs()
    elif len(sys.argv) > 1 and sys.argv[1] == 'stats':
        import json
        print(json.dumps(get_stats(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == 'today':
        orders = get_today_orders()
        for o in orders:
            print(f"  [{o['status']}] {o['side'].upper()} {o['symbol']} x{o['qty']}  {o.get('strategy','-')}")
    else:
        orders = get_orders(limit=20)
        print(f"订单管理器: {len(orders)}条最新")
        for o in orders[:10]:
            print(f"  #{o['intent_id'][-12:]} [{o['status']:10s}] {o['side'].upper():4s} {o['symbol']:6s} x{o['qty']:3d} {o.get('strategy','-')}")
