"""
交易记录 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

bp = Blueprint("trades", __name__, url_prefix="/trades")


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
    return render_template("trades.html")


@bp.route("/api/trade_log")
def api_trade_log():
    """读取交易记录"""
    import os, json
    log_file = "signals/trade_log.json"
    if os.path.exists(log_file):
        with open(log_file) as f:
            logs = json.load(f)
        return jsonify(_fix({"trades": logs, "total": len(logs)}))
    return jsonify({"trades": [], "total": 0})


@bp.route("/api/portfolio_history")
def api_portfolio_history():
    """从日报文件读取历史权益"""
    import os, glob
    history = []
    reports_dir = "signals/reports"
    if os.path.exists(reports_dir):
        for f in sorted(glob.glob(f"{reports_dir}/report_*.txt")):
            date = os.path.basename(f).replace("report_", "").replace(".txt", "")
            content = open(f).read()
            for line in content.split("\n"):
                if "权益:" in line:
                    try:
                        eq = float(line.split("$")[1].replace(",", ""))
                        history.append({"date": date, "equity": eq})
                    except:
                        pass
                    break
    return jsonify(_fix(history))


@bp.route("/api/attribution")
def api_attribution():
    """绩效归因"""
    from performance_attribution import get_stats
    try:
        report = get_stats()
        return jsonify(_fix(report))
    except Exception as e:
        return jsonify({"error": str(e)})


@bp.route("/api/stats")
def api_stats():
    """交易统计"""
    import os, json
    log_file = "signals/trade_log.json"
    trades = []
    if os.path.exists(log_file):
        with open(log_file) as f:
            trades = json.load(f)

    buys = [t for t in trades if t.get("side", "").upper() == "BUY"]
    sells = [t for t in trades if t.get("side", "").upper() == "SELL"]

    total_buy = sum(t.get("value", 0) for t in buys)
    total_sell = sum(t.get("value", 0) for t in sells)
    total_trades = len(trades)

    # 按股票统计
    by_symbol = {}
    for t in trades:
        sym = t.get("symbol", "?")
        if sym not in by_symbol:
            by_symbol[sym] = {"buy_count": 0, "sell_count": 0, "buy_value": 0, "sell_value": 0}
        if t.get("side", "").upper() == "BUY":
            by_symbol[sym]["buy_count"] += 1
            by_symbol[sym]["buy_value"] += t.get("value", 0)
        else:
            by_symbol[sym]["sell_count"] += 1
            by_symbol[sym]["sell_value"] += t.get("value", 0)

    return jsonify(_fix({
        "total_trades": total_trades,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_buy_volume": total_buy,
        "total_sell_volume": total_sell,
        "by_symbol": by_symbol,
    }))
