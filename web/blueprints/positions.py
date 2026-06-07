"""
持仓看板 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
import logging

logger = logging.getLogger("quant.positions")
bp = Blueprint("positions", __name__, url_prefix="/positions")


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
    return render_template("positions.html")


@bp.route("/api/data")
def api_positions():
    """从Alpaca实时拉取持仓数据"""
    from portfolio_tracker import sync_from_alpaca
    try:
        portfolio = sync_from_alpaca()
    except Exception as e:
        logger.error(f"持仓实时同步失败: {e}")
        portfolio = {"equity": 0, "cash": 0, "positions": {}, "position_count": 0}

    positions = list(portfolio.get("positions", {}).values()) if portfolio.get("positions") else []

    total_cost = sum(p.get("cost_basis", 0) for p in positions)
    total_value = sum(p.get("market_value", 0) for p in positions)
    total_pnl = sum(p.get("pnl_amount", 0) for p in positions)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return jsonify(_fix({
        "equity": portfolio.get("equity", 0),
        "cash": portfolio.get("cash", 0),
        "positions": positions,
        "summary": {
            "count": len(positions),
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "exposure_pct": ((total_value) / max(portfolio.get("equity", 1), 1)) * 100,
        }
    }))


@bp.route("/api/trade_log")
def api_trade_log():
    """交易记录"""
    import os, json
    log_file = "signals/trade_log.json"
    if os.path.exists(log_file):
        with open(log_file) as f:
            logs = json.load(f)
        return jsonify(logs[-50:])
    return jsonify([])


@bp.route("/api/close_all", methods=["POST"])
def api_close_all():
    """一键清仓"""
    from paper_trader import close_all
    try:
        close_all()
        return jsonify({"status": "ok", "message": "清仓指令已发送"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
