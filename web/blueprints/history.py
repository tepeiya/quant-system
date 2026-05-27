"""
信号历史 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

bp = Blueprint("history", __name__, url_prefix="/history")


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
    return render_template("history.html")


@bp.route("/api/list")
def api_list():
    """读取所有历史信号文件"""
    import os, glob, json
    files = sorted(glob.glob("signals/signal_*.json"), reverse=True)
    signals = []
    for f in files[:90]:  # 最近90天
        try:
            with open(f) as fp:
                data = json.load(fp)
            date = data.get("date", "?")
            market = data.get("market", {})
            top = data.get("top_scores", [])
            candidates = data.get("buy_candidates", [])

            signals.append({
                "date": date,
                "trend": market.get("trend", "?"),
                "action": market.get("action", "?"),
                "top3": [s["ticker"] for s in top[:3]],
                "candidate_count": len(candidates),
                "top_score": top[0]["score"] if top else 0,
            })
        except:
            pass
    return jsonify(_fix({"signals": signals, "total": len(signals)}))


@bp.route("/api/detail")
def api_detail():
    """读取某一天信号的完整详情"""
    date = __import__("flask").request.args.get("date", "")
    if not date:
        return jsonify({"error": "需要 date 参数"})

    import os, glob, json
    for f in sorted(glob.glob("signals/signal_*.json"), reverse=True):
        if date in f:
            with open(f) as fp:
                data = json.load(fp)
            return jsonify(_fix(data))
    return jsonify({"error": f"未找到 {date} 的信号"})
