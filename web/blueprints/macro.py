"""
宏观仪表盘 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
from datetime import datetime

bp = Blueprint("macro", __name__, url_prefix="/macro")


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
    return render_template("macro.html")


@bp.route("/api/data")
def api_macro():
    """宏观因子数据"""
    from macro_monitor import macro_summary
    try:
        m = macro_summary()
    except:
        m = {"total_score": 0, "verdict": "⚪", "advice": "数据不可用",
             "bond": {"score": 0, "10y_yield": 0, "10y2y_spread": 0, "inverted": False},
             "dollar": {"score": 0, "dxy": 0},
             "gold": {"score": 0, "gld": 0},
             "inflation": {"score": 0, "cpi_yoy": 0}}
    return jsonify(_fix(m))
