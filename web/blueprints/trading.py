"""
手动下单 - Blueprint
"""
from flask import Blueprint, jsonify, render_template, request, session
import numpy as np
from security import log_audit, csrf_protect

bp = Blueprint("trading", __name__, url_prefix="/trading")


def _fix(obj):
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@bp.route("/")
def page():
    return render_template("trading.html")


@bp.route("/api/preview", methods=["POST"])
def api_preview():
    from broker_manager import BrokerManager
    bm = BrokerManager()
    broker = bm.get_current()
    acct = broker.get_account()
    return jsonify(_fix(acct))


@bp.route("/api/submit", methods=["POST"])
@csrf_protect
def api_submit():
    data = request.json or {}
    symbol = data.get("symbol", "").upper().strip()
    side = data.get("side", "buy").lower()
    qty = int(data.get("qty", 0))
    if not symbol or qty <= 0:
        return jsonify({"status": "error", "message": "参数错误"})
    try:
        from broker_manager import BrokerManager
        bm = BrokerManager(username=session.get("user"))
        broker = bm.get_current()
        result = broker.submit_order(symbol, qty, side, "market")
        log_audit("ORDER", session.get("user", "?"), f"{side.upper()} {symbol} x{qty}")
        return jsonify(_fix(result))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@bp.route("/api/search", methods=["POST"])
def api_search():
    data = request.json or {}
    keyword = data.get("keyword", "").strip().upper()
    if not keyword:
        return jsonify([])
    from data_prod import load_price_cache
    cache = load_price_cache()
    results = []
    for t in cache:
        if keyword in t:
            df = cache[t]
            price = df["Close"].iloc[-1] if df is not None else 0
            change = (price / df["Close"].iloc[-2] - 1) * 100 if df is not None and len(df) > 1 else 0
            results.append({"symbol": t, "price": round(float(price), 2), "change": round(float(change), 2)})
            if len(results) >= 10:
                break
    return jsonify(_fix(sorted(results, key=lambda x: x["symbol"])))
