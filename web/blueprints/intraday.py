"""
日内交易 Web API — 独立于其他蓝图
"""
from flask import Blueprint, jsonify, render_template, make_response
import os, json, logging
from api_response import ok, err

logger = logging.getLogger("quant.intraday_web")
bp = Blueprint("intraday", __name__, url_prefix="/intraday")


def _get_intraday_client():
    """获取日内专用Alpaca客户端"""
    from alpaca.trading.client import TradingClient
    from broker_manager import BrokerManager, load_config
    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id("intraday")
    cfg = load_config().get(broker_id, {})
    key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
    secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
    if not key or not secret:
        return None, None
    return TradingClient(key, secret, paper=cfg.get("paper", True)), broker_id


@bp.route("/")
@bp.route("/page")
def page():
    resp = make_response(render_template("intraday.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@bp.route("/api/allocation")
def api_allocation():
    """资金分配状态"""
    equity = 0
    cash = 0
    allocated = 0
    ratio = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))
    used = 0
    position_count = 0

    try:
        client, broker_id = _get_intraday_client()
        if client:
            acct = client.get_account()
            equity = float(acct.equity)
            cash = float(acct.cash)
            allocated = equity

            total_pnl = 0
            for p in client.get_all_positions():
                qty = int(float(p.qty))
                if qty > 0:
                    position_count += 1
                    used += float(p.market_value)
                    total_pnl += float(p.unrealized_pl)
        else:
            ratio = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))
            from alpaca.trading.client import TradingClient
            from broker_manager import load_config, get_default_broker_id
            cfg = load_config().get(get_default_broker_id(), {})
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
            if key and secret:
                client2 = TradingClient(key, secret, paper=True)
                acct = client2.get_account()
                equity = float(acct.equity)
                cash = float(acct.cash)
                allocated = equity * ratio
    except Exception as e:
        logger.error(f"获取分配信息失败: {e}")

    return jsonify({
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "allocated": round(allocated, 2),
        "ratio": ratio,
        "used": round(used, 2),
        "available": round(max(allocated - used, 0), 2),
        "positions": position_count,
        "today_trades": 0,
        "pnl": round(total_pnl, 2) if 'total_pnl' in dir() else 0,
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
        sig = generate_signal()
        bt = run_backtest(days=252)
        return ok({"candidates": sig.get("candidates", []), "backtest": bt})
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
        total_pnl = 0
        for p in client.get_all_positions():
            qty = int(float(p.qty))
            if qty > 0:
                pnl = float(p.unrealized_pl)
                total_pnl += pnl
                positions.append({
                    "symbol": p.symbol,
                    "qty": qty,
                    "current_price": round(float(p.current_price), 2),
                    "avg_entry": round(float(p.avg_entry_price), 2),
                    "pnl_pct": round(float(p.unrealized_plpc) * 100, 2),
                    "pnl": round(pnl, 2),
                    "market_value": round(float(p.market_value), 2),
                })
        return jsonify({"positions": positions, "total_pnl": round(total_pnl, 2)})
    except Exception as e:
        return jsonify({"positions": [], "error": str(e)})


@bp.route("/api/check_stop", methods=["POST"])
def api_check_stop():
    """手动触发止盈止损检查"""
    from intraday_trader import check_stop_loss
    try:
        check_stop_loss()
        return ok(message="止盈止损检查完成")
    except Exception as e:
        return err(str(e))
