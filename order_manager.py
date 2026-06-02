import os, json, time, logging
from datetime import datetime

logger = logging.getLogger('quant.order')
ORDERS_FILE = 'signals/orders_state.json'

STATUS_NEW='NEW'
STATUS_SUBMITTED='SUBMITTED'
STATUS_PARTIAL='PARTIAL'
STATUS_FILLED='FILLED'
STATUS_REJECTED='REJECTED'
STATUS_CANCELED='CANCELED'


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


def new_intent(symbol, side, qty, broker='alpaca'):
    rows = _load()
    oid = f"{int(time.time()*1000)}_{symbol}_{side}"
    row = {
        'intent_id': oid, 'symbol': symbol, 'side': side, 'qty': qty,
        'broker': broker, 'status': STATUS_NEW, 'created_at': str(datetime.now()),
        'retry_count': 0, 'last_error': None
    }
    rows.append(row)
    _save(rows)
    return row


def mark(intent_id, status, **kwargs):
    rows = _load()
    for r in rows:
        if r.get('intent_id') == intent_id:
            r['status'] = status
            r.update(kwargs)
            r['updated_at'] = str(datetime.now())
            break
    _save(rows)


def retry_failed(submit_func, max_retry=3):
    """对失败/新建订单做简单重试，submit_func(intent)->result"""
    rows = _load()
    for r in rows:
        if not can_retry(r, max_retry=max_retry):
            continue
        if r.get('status') not in [STATUS_NEW, STATUS_REJECTED]:
            continue
        try:
            result = submit_func(r)
            if isinstance(result, dict) and result.get('error'):
                r['retry_count'] = r.get('retry_count', 0) + 1
                r['last_error'] = result.get('error')
                r['status'] = STATUS_REJECTED
            else:
                r['status'] = STATUS_SUBMITTED
                r['broker_order'] = result
                r['retry_count'] = r.get('retry_count', 0)
            r['updated_at'] = str(datetime.now())
        except Exception as e:
            r['retry_count'] = r.get('retry_count', 0) + 1
            r['last_error'] = str(e)
            r['status'] = STATUS_REJECTED
            r['updated_at'] = str(datetime.now())
    _save(rows)
    return rows


def mark_filled(intent_id, filled_qty=None, avg_price=None):
    mark(intent_id, STATUS_FILLED, filled_qty=filled_qty, avg_fill_price=avg_price)


def mark_partial(intent_id, filled_qty=None, avg_price=None):
    mark(intent_id, STATUS_PARTIAL, filled_qty=filled_qty, avg_fill_price=avg_price)
