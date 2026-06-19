"""
大盘仪表盘 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

import os, json, logging
logger = logging.getLogger("quant.dashboard")

from api_response import ok, err


def get_broker():
    """获取当前用户的Broker实例"""
    from flask import session
    from broker_manager import BrokerManager
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


bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


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
        from portfolio_tracker import sync_from_alpaca
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
        from macro_monitor import macro_summary
        macro = macro_summary()
    except Exception as e:
        logger.warning(f"dashboard宏观失败，使用默认: {str(e)[:80]}")

    payload = _fix({
        "portfolio": portfolio,
        "macro": macro,
        "intraday": _get_intraday_info(),
    })
    return jsonify(payload)


def _get_intraday_info() -> dict:
    """获取日内交易账户详情"""
    result = {
        "allocated": 0,
        "ratio": 0,
        "used": 0,
        "positions": 0,
        "pnl": 0,
        "today_trades": 0,
        "mode": "shared",
    }
    try:
        from alpaca.trading.client import TradingClient
        from broker_manager import BrokerManager, load_config

        bm = BrokerManager()
        ratio = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))

        # 检查是否有启用的日内专用券商
        intraday_broker_id = bm.get_strategy_broker_id("intraday")
        cfg = load_config().get(intraday_broker_id, {})
        dedicated_enabled = cfg.get("enabled", False) and bool(os.environ.get(cfg.get("env_key_id", ""), ""))

        if dedicated_enabled:
            # 专用账户模式：直接读专用账户的全部权益
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
            client = TradingClient(key, secret, paper=cfg.get("paper", True))
            acct = client.get_account()
            equity = float(acct.equity)
            allocated = equity
            ratio = 1.0
        else:
            # 共享模式：从主账户按比例分配
            main_broker_id = bm.get_strategy_broker_id("conservative")
            cfg = load_config().get(main_broker_id, {})
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")

        positions = []
        pos_value = 0
        pos_pnl = 0
        try:
            client = TradingClient(key, secret, paper=cfg.get("paper", True))
            acct = client.get_account()
            equity = float(acct.equity)
            allocated = equity * ratio if not dedicated_enabled else equity
            positions = client.get_all_positions()
            pos_value = sum(float(p.market_value) for p in positions) if positions else 0
            pos_pnl = sum(float(p.unrealized_pl) for p in positions) if positions else 0
        except:
            pass

        # 今日日内交易次数
        today_trades = 0
        if os.path.exists("signals/intraday_trades.json"):
            with open("signals/intraday_trades.json") as f:
                log = json.load(f)
            today = str(datetime.now().strftime("%Y-%m-%d"))
            today_trades = sum(1 for t in log.get("trades", []) if today in str(t.get("time", "")))

        result = {
            "allocated": round(allocated, 2),
            "ratio": ratio,
            "used": round(pos_value, 2),
            "available": round(allocated - pos_value, 2),
            "positions": len(positions) if positions else 0,
            "pnl": round(pos_pnl, 2),
            "today_trades": today_trades,
        }
    except:
        pass
    return result


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
