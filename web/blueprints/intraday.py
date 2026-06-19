"""
日内交易 Web API — 独立于其他蓝图
"""
from flask import Blueprint, jsonify, render_template, make_response
import os, json, logging
from api_response import ok, err
import numpy as np

logger = logging.getLogger("quant.intraday_web")
bp = Blueprint("intraday", __name__, url_prefix="/intraday")


@bp.route("/")
@bp.route("/page")
def page():
    resp = make_response(render_template("intraday.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@bp.route("/api/allocation")
def api_allocation():
    """资金分配状态"""
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
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
            client = TradingClient(key, secret, paper=cfg.get("paper", True))
            acct = client.get_account()
            equity = float(acct.equity)
            allocated = equity
        else:
            main_broker_id = bm.get_strategy_broker_id("conservative")
            cfg = load_config().get(main_broker_id, {})
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
            client = TradingClient(key, secret, paper=cfg.get("paper", True))
            acct = client.get_account()
            equity = float(acct.equity)
            allocated = equity * ratio
        client = TradingClient(key, secret, paper=cfg.get("paper", True))
        acct = client.get_account()
        equity = float(acct.equity)
        cash = float(acct.cash)
    except:
        equity, cash = 0, 0

    ratio = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))
    allocated = equity * ratio
    used = 0
    pos_list = []
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(
            os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), ""),
            os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), ""),
            paper=True)
        for p in client.get_all_positions():
            pos_list.append(p.symbol)
            used += float(p.market_value)
    except:
        pass

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "allocated": round(allocated, 2),
        "ratio": ratio,
        "used": round(used, 2),
        "available": round(max(allocated - used, 0), 2),
        "positions": len(pos_list),
    })


@bp.route("/api/signals")
def api_signals():
    """今日信号"""
    signal = {}
    if os.path.exists("signals/intraday_signal.json"):
        with open("signals/intraday_signal.json") as f:
            signal = json.load(f)
    return jsonify(signal)


@bp.route("/api/backtest")
def api_backtest():
    """回测结果"""
    result = {}
    if os.path.exists("signals/intraday_backtest.json"):
        with open("signals/intraday_backtest.json") as f:
            result = json.load(f)
    return jsonify(result)


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    """扫描日内信号"""
    import subprocess, sys, json
    try:
        # 用 subprocess 调用策略模块，避免导入冲突
        r = subprocess.run(
            [sys.executable, "-c", 
             "import sys, json; sys.path.insert(0, '.'); "
             "from intraday import generate_signal, run_backtest; "
             "sig = generate_signal(); "
             "bt = run_backtest(days=365); "
             "import os; os.makedirs('signals', exist_ok=True); "
             "json.dump(sig, open('signals/intraday_signal.json','w')); "
             "json.dump(bt, open('signals/intraday_backtest.json','w')); "
             "print(json.dumps(sig))"],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return jsonify(json.loads(r.stdout))
        else:
            return err(r.stderr[:200])
    except Exception as e:
        return err(str(e))


@bp.route("/api/execute", methods=["POST"])
def api_execute():
    """执行日内交易"""
    from intraday_trader import execute_intraday
    try:
        execute_intraday(auto=True)
        return ok(message="日内交易已执行")
    except Exception as e:
        return err(str(e))


@bp.route("/api/close_all", methods=["POST"])
def api_close_all():
    """强制清仓"""
    from intraday_trader import close_all
    try:
        close_all(auto=True)
        return ok(message="日内持仓已清仓")
    except Exception as e:
        return err(str(e))


@bp.route("/api/positions")
def api_positions():
    """获取日内持仓"""
    try:
        from intraday_trader import get_alpaca
        client = get_alpaca()
        positions = []
        for p in client.get_all_positions():
            qty = int(float(p.qty))
            if qty > 0:
                positions.append({
                    "symbol": p.symbol,
                    "qty": qty,
                    "current_price": round(float(p.current_price), 2),
                    "avg_entry": round(float(p.avg_entry_price), 2),
                    "pnl_pct": round(float(p.unrealized_plpc) * 100, 2),
                    "market_value": round(float(p.market_value), 2),
                })
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"positions": [], "error": str(e)})
