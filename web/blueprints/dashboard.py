"""
大盘仪表盘 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

import os, json, logging
logger = logging.getLogger("quant.dashboard")

from broker_manager import BrokerManager
from portfolio_tracker import sync_from_alpaca
from api_response import ok, err


def get_broker():
    """获取当前用户的Broker实例"""
    from flask import session
    username = session.get("user")
    bm = BrokerManager(username=username)
    return bm.get_current()


CACHED_PORTFOLIO_FILE = "signals/cached_portfolio.json"


def load_cached_portfolio() -> dict:
    if os.path.exists(CACHED_PORTFOLIO_FILE):
        try:
            with open(CACHED_PORTFOLIO_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"equity": 0, "cash": 0, "positions": {}, "position_count": 0}


def save_cached_portfolio(data: dict):
    os.makedirs("signals", exist_ok=True)
    with open(CACHED_PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2)


from macro_monitor import macro_summary
from daily_signal import generate_signals

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")
broker = BrokerManager()


def _fix(obj):
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_fix(v) for v in obj)
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
    return render_template("dashboard.html")


@bp.route("/api/data")
def api_data():
    from flask import session
    username = session.get("user")

    # 默认兜底（永不返回空）
    portfolio = {
        "equity": 0,
        "cash": 0,
        "position_count": 0,
        "positions": {}
    }

    macro = {
        "total_score": 0,
        "verdict": "⚪",
        "bond": {"score": 0},
        "dollar": {"score": 0},
        "gold": {"score": 0},
        "inflation": {"score": 0}
    }

    # 1) 先尝试读缓存
    try:
        cached = load_cached_portfolio()
        if cached and cached.get("equity") is not None:
            portfolio = cached
    except:
        pass

    # 2) 再尝试实时同步（失败不影响）
    try:
        p = sync_from_alpaca(username=username)
        if p and p.get("equity") is not None:
            portfolio = p
            try:
                with open(CACHED_PORTFOLIO_FILE, "w") as f:
                    json.dump(portfolio, f, ensure_ascii=False, indent=2)
            except:
                pass
    except Exception as e:
        logger.warning(f"dashboard实时同步失败，使用缓存: {str(e)[:80]}")

    # 3) 宏观失败也兜底
    try:
        macro = macro_summary()
    except Exception as e:
        logger.warning(f"dashboard宏观失败，使用默认: {str(e)[:80]}")

    payload = _fix({
        "portfolio": portfolio,
        "macro": macro,
    })
    return jsonify(payload)


@bp.route("/api/equity_history")
def api_equity_history():
    """资金曲线历史"""
    history = []
    import os, glob
    reports_dir = "signals/reports"
    if os.path.exists(reports_dir):
        for f in sorted(glob.glob(f"{reports_dir}/report_*.txt")):
            date = os.path.basename(f).replace("report_", "").replace(".txt", "")
            with open(f) as fh:
                content = fh.read()
            for line in content.split("\n"):
                if "权益:" in line:
                    try:
                        eq = float(line.split("$")[1].replace(",", ""))
                        history.append({"date": date, "equity": eq})
                    except:
                        pass
                    break
    return jsonify(history[-90:])
