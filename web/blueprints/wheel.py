"""
轮式期权策略 - Blueprint
"""
from flask import Blueprint, jsonify, render_template, request
import numpy as np

bp = Blueprint("wheel", __name__, url_prefix="/wheel")


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
    return render_template("wheel.html")


@bp.route("/api/plan")
def api_plan():
    """生成轮式计划"""
    from wheel_strategy import generate_wheel_plan
    try:
        plan = generate_wheel_plan()
        return jsonify(_fix(plan))
    except Exception as e:
        return jsonify({"error": str(e)})


@bp.route("/api/status")
def api_status():
    """当前状态"""
    from wheel_strategy import get_status
    return jsonify(_fix(get_status()))


@bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    """读取/更新配置"""
    from wheel_strategy import load_config, save_config
    if request.method == "POST":
        data = request.json or {}
        cfg = load_config()
        for k, v in data.items():
            if k in cfg:
                cfg[k] = v
        save_config(cfg)
        return jsonify({"status": "ok", "config": {k: v for k, v in cfg.items() if k != "enabled"}})
    cfg = load_config()
    return jsonify(_fix({k: v for k, v in cfg.items() if k != "enabled"}))


@bp.route("/api/execute", methods=["POST"])
def api_execute():
    """执行轮式计划"""
    from wheel_strategy import generate_wheel_plan, execute_wheel_plan
    plan = generate_wheel_plan()
    result = execute_wheel_plan(plan, auto=True)
    return jsonify(_fix(result))
