"""
配对交易 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

bp = Blueprint("pairs", __name__, url_prefix="/pairs")


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
    return render_template("pairs.html")


@bp.route("/api/scan")
def api_scan():
    """扫描配对"""
    from data_prod import load_price_cache
    from pairs_trading import scan_pairs, generate_pair_signals

    try:
        cache = load_price_cache()
        pairs = scan_pairs(cache)
        signals = generate_pair_signals(cache, pairs)
        return jsonify(_fix({
            "pairs": pairs[:20],
            "signals": signals,
        }))
    except Exception as e:
        return jsonify({"error": str(e)})


@bp.route("/api/signals")
def api_signals():
    """获取信号"""
    from data_prod import load_price_cache
    from pairs_trading import generate_pair_signals

    try:
        cache = load_price_cache()
        signals = generate_pair_signals(cache)
        return jsonify(_fix({"signals": signals}))
    except Exception as e:
        return jsonify({"error": str(e)})


@bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    """读取/更新配置"""
    from pairs_trading import load_config, save_config
    if __import__("flask").request.method == "POST":
        data = __import__("flask").request.json or {}
        cfg = load_config()
        for k, v in data.items():
            if k in cfg:
                cfg[k] = v
        save_config(cfg)
        return jsonify({"status": "ok"})
    return jsonify(load_config())
