from flask import Blueprint, jsonify, render_template
import json
import os

bp = Blueprint("allocator", __name__, url_prefix="/allocator")


@bp.route("/")
def page():
    return render_template("allocator.html")


@bp.route("/api/execute", methods=["POST"])
def api_execute():
    from multi_strategy_runner import run_all
    try:
        return jsonify(run_all(auto=True))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@bp.route("/api/report")
def api_report():
    from strategy_allocator import allocation_report
    from portfolio_tracker import load_portfolio

    # 最新信号市场状态
    market = {"trend": "⚪", "action": "部分仓位"}
    try:
        import glob
        files = sorted(glob.glob("signals/signal_*.json"))
        if files:
            with open(files[-1]) as f:
                sig = json.load(f)
            market = sig.get("market", market)
    except:
        pass

    p = load_portfolio() or {}
    equity = float(p.get("equity", 0) or 0)
    cash = float(p.get("cash", 0) or 0)

    rep = allocation_report(market, equity, cash)
    rep["market"] = market
    return jsonify(rep)
