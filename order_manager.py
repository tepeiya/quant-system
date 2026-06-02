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


def can_retry(intent, max_retry=3):
    return intent.get('retry_count', 0) < max_retry and intent.get('status') in [STATUS_NEW, STATUS_SUBMITTED, STATUS_PARTIAL, STATUS_REJECTED]
