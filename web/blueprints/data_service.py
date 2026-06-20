"""
数据服务看板 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
from security import csrf_protect
import sys, os, signal_bus

bp = Blueprint("data_service", __name__, url_prefix="/data")


@bp.route("/")
def data_page():
    return render_template("data_service.html")


@bp.route("/api/health")
def api_health():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from data_service import check_health
    return jsonify(check_health())


@bp.route("/api/update", methods=["POST"])
@csrf_protect
def api_update():
    """手动触发更新"""
    data = __import__("flask").request.json or {}
    full = data.get("full", False)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from data_service import run_update
    try:
        result = run_update(full=full)
        if result:
            return ok(message="数据更新完成")
        return err("更新失败")
    except Exception as e:
        return err(str(e))


@bp.route("/api/status")
def api_status():
    """数据总线最近消息"""
    msgs = signal_bus.get_recent_messages(5)
    data_updates = [m for m in msgs if m["msg_type"] == "data_update"]
    return jsonify({
        "recent_updates": data_updates[:3] if data_updates else [],
        "total_messages": signal_bus.get_pending_count(),
    })
