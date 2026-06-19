"""
因子追踪 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
from datetime import datetime, timedelta

bp = Blueprint("factors", __name__, url_prefix="/factors")


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
    return render_template("factors.html")


@bp.route("/api/weights")
def api_weights():
    """读取当前因子权重"""
    import os, json
    config_file = "config/factor_weights.json"
    if os.path.exists(config_file):
        with open(config_file) as f:
            weights = json.load(f)
    else:
        weights = {"momentum": 55, "quality": 25, "trend": 20}
    return jsonify(_fix(weights))


@bp.route("/api/update_weights", methods=["POST"])
def api_update_weights():
    """更新因子权重"""
    import os, json
    data = __import__("flask").request.json or {}
    weights = data.get("weights", {})
    if not weights:
        return jsonify({"status": "error", "message": "缺少权重参数"})

    total = sum(weights.values())
    if total != 100:
        return jsonify({"status": "error", "message": f"权重总和应为100，当前{total}"})

    os.makedirs("config", exist_ok=True)
    with open("config/factor_weights.json", "w") as f:
        json.dump(weights, f, indent=2)

    # 自动记录版本
    from version_manager import snapshot
    snapshot(label=f"Web面板修改: {weights}")

    return jsonify({"status": "ok", "message": f"权重已更新: {weights}"})


@bp.route("/api/evolution_history")
def api_evolution_history():
    """进化历史"""
    import os, json
    evol_file = "config/factor_evolution.json"
    if os.path.exists(evol_file):
        with open(evol_file) as f:
            history = json.load(f)
    else:
        history = []
    return jsonify({"history": _fix(history)})


@bp.route("/api/evolve", methods=["POST"])
def api_evolve():
    """执行因子自动进化"""
    import subprocess, sys, os, json
    try:
        result = subprocess.run(
            [sys.executable, "factor_learner.py", "--apply"],
            capture_output=True, text=True, timeout=90,
            env={**os.environ}
        )
        output = (result.stdout + result.stderr)[-300:]
        if result.returncode == 0:
            return jsonify({"status": "ok", "message": "因子进化完成！权重已自动更新", "output": output})
        else:
            return jsonify({"status": "error", "message": "进化失败", "output": output})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:100]})


@bp.route("/api/ic_history")
def api_ic_history():
    """因子IC历史——快速版：读取缓存的进化结果"""
    import os, json
    # 优先从进化历史读取
    evol_file = "config/factor_evolution.json"
    if os.path.exists(evol_file):
        with open(evol_file) as f:
            history = json.load(f)
        if history:
            latest = history[-1]
            monthly = latest.get("monthly_ics", [])
            if monthly:
                result = []
                for m in monthly:
                    result.append({
                        "month": m.get("_month", ""),
                        "momentum_ic": m.get("momentum", 0),
                        "quality_ic": m.get("quality", 0),
                        "trend_ic": m.get("trend", 0),
                    })
                return jsonify(_fix(result))

    # 无数据时返回空
    return jsonify([])


@bp.route("/api/ranking")
def api_ranking():
    """读取因子排名"""
    import os, json
    ranking_file = "config/factor_ranking.json"
    if os.path.exists(ranking_file):
        with open(ranking_file) as f:
            data = json.load(f)
        return jsonify(_fix(data))
    return jsonify({"factors": [], "top_factors": [], "timestamp": ""})


@bp.route("/api/run_ranking", methods=["POST"])
def api_run_ranking():
    """重新计算因子排名"""
    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, "factor_ranking.py"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ}
        )
        output = (result.stdout + result.stderr)[-500:]
        if result.returncode == 0:
            return jsonify({"status": "ok", "message": "因子排名计算完成"})
        else:
            return jsonify({"status": "error", "message": "计算失败", "output": output})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:100]})
