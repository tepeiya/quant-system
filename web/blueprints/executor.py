"""
执行器控制 - Blueprint
统一交易执行器的Web控制面板
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
from security import csrf_protect
import json, os, signal_bus

bp = Blueprint("executor", __name__, url_prefix="/executor")


@bp.route("/")
def executor_page():
    return render_template("executor.html")


@bp.route("/api/status")
def api_status():
    """获取执行器状态"""
    bus = signal_bus.get_bus_status()
    # 读取执行器心跳
    heartbeats = signal_bus.get_strategy_heartbeats()
    return jsonify({
        "pending": bus.get("pending", 0),
        "strategies": heartbeats,
        "recent": bus.get("recent", []),
    })


@bp.route("/api/run_once", methods=["POST"])
@csrf_protect
def api_run_once():
    """手动执行一次"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from executor import TradeExecutor
        ex = TradeExecutor()
        results = ex.run_once(dry_run=False)
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        return err(str(e))


@bp.route("/api/dry_run", methods=["POST"])
@csrf_protect
def api_dry_run():
    """模拟执行一次"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from executor import TradeExecutor
        ex = TradeExecutor()
        results = ex.run_once(dry_run=True)
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        return err(str(e))


@bp.route("/api/bus_messages")
def api_bus_messages():
    """获取最新总线消息"""
    return jsonify(signal_bus.get_recent_messages(30))
