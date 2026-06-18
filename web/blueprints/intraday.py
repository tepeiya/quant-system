"""
日内交易 Web API — 独立于其他蓝图
"""
from flask import Blueprint, jsonify, render_template
import os, json, logging
from api_response import ok, err
import numpy as np

logger = logging.getLogger("quant.intraday_web")
bp = Blueprint("intraday", __name__, url_prefix="/intraday")


@bp.route("/")
def page():
    return render_template("intraday.html")


@bp.route("/api/allocation")
def api_allocation():
    """资金分配状态"""
    try:
        from alpaca.trading.client import TradingClient
        from broker_manager import BrokerManager, load_config
        bm = BrokerManager()
        broker_id = bm.get_strategy_broker_id("intraday")
        cfg = load_config().get(broker_id, {})
        key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
        secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
        client = TradingClient(key, secret, paper=cfg.get("paper", True))
        acct = client.get_account()
        equity = float(acct.equity)
        cash = float(acct.cash)
    except:
        equity, cash = 0, 0

    ratio = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))
    allocated = equity * ratio
    used = 0
    positions = []
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(
            os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), ""),
            os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), ""),
            paper=True)
        for p in client.get_all_positions():
            positions.append(p.symbol)
    except:
        pass

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "allocated": round(allocated, 2),
        "ratio": ratio,
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
    from intraday import generate_signal, run_backtest
    try:
        signal = generate_signal()
        # 同时跑回测
        backtest = run_backtest(days=365)
        os.makedirs("signals", exist_ok=True)
        with open("signals/intraday_backtest.json", "w") as f:
            json.dump(backtest, f, indent=2)
        return jsonify(signal)
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
