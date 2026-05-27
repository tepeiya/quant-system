"""
信号看板 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

from daily_signal import generate_signals

bp = Blueprint("signals", __name__, url_prefix="/signals")


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
    return render_template("signals.html")


@bp.route("/api/today")
def api_today():
    """今日信号——快速模式：只读缓存，不联网"""
    import os, json
    # 先找今日已生成的信号文件
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    signal_file = f"signals/signal_{today}.json"
    if os.path.exists(signal_file):
        with open(signal_file) as f:
            return jsonify(_fix(json.load(f)))
    
    # 没有今日信号就找最新的
    import glob
    files = sorted(glob.glob("signals/signal_*.json"))
    if files:
        with open(files[-1]) as f:
            return jsonify(_fix(json.load(f)))
    
    return jsonify({"error": "无信号数据，请先生成"})


@bp.route("/api/execute", methods=["POST"])
def api_execute():
    """执行调仓"""
    from paper_trader import rebalance
    try:
        rebalance(auto=True)
        return jsonify({"status": "ok", "message": "调仓完成"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
