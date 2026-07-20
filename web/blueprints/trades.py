"""
交易记录 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
import os, json

bp = Blueprint("trades", __name__, url_prefix="/trades")


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


def _load_json(path, default):
    """安全加载 JSON 文件"""
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _collect_trades():
    """合并所有交易记录数据源

    数据源优先级:
    1. signals/trade_log.json          (保守策略, portfolio_tracker写入)
    2. signals/trade_log_momentum.json (激进策略, paper_trader_momentum写入)
    3. signals/intraday_trades.json    (日内策略, intraday_trader写入)
    4. signals/orders_state.json       (订单管理器的订单, 取已FILLED的)
    5. database.trades 表              (数据库, trade_executor写入)
    """
    trades = []

    # 1. 保守策略交易日志
    log = _load_json("signals/trade_log.json", [])
    if isinstance(log, list):
        for t in log:
            if isinstance(t, dict):
                t.setdefault("strategy", "conservative")
                t.setdefault("source", "trade_log")
                trades.append(t)

    # 2. 激进策略交易日志
    log_m = _load_json("signals/trade_log_momentum.json", [])
    if isinstance(log_m, list):
        for t in log_m:
            if isinstance(t, dict):
                t.setdefault("strategy", "momentum")
                t.setdefault("source", "trade_log_momentum")
                trades.append(t)

    # 3. 日内策略交易日志 (嵌套结构 {"trades": [{time, action, trades:[{symbol,side,qty,price}]}, ...]})
    log_i = _load_json("signals/intraday_trades.json", None)
    if log_i is not None:
        outer_trades = []
        if isinstance(log_i, dict):
            outer_trades = log_i.get("trades", [])
        elif isinstance(log_i, list):
            for entry in log_i:
                if isinstance(entry, dict) and "trades" in entry:
                    outer_trades.append(entry)
                elif isinstance(entry, dict):
                    outer_trades.append({"time": entry.get("time", ""), "trades": [entry]})
        # 展平嵌套结构
        for entry in outer_trades:
            if not isinstance(entry, dict):
                continue
            entry_time = entry.get("time", "")
            entry_action = entry.get("action", "")
            inner_trades = entry.get("trades", [])
            if not isinstance(inner_trades, list):
                continue
            for t in inner_trades:
                if not isinstance(t, dict):
                    continue
                price = t.get("price", 0)
                qty = t.get("qty", 0)
                trades.append({
                    "time": entry_time,
                    "symbol": t.get("symbol", "?"),
                    "side": (t.get("side", "") or "").upper(),
                    "qty": qty,
                    "price": price,
                    "value": float(qty) * float(price) if price else 0,
                    "strategy": "intraday",
                    "source": "intraday_trades",
                    "action": entry_action,
                    "auto": t.get("auto", False),
                })

    # 4. 订单管理器中已成交订单
    orders = _load_json("signals/orders_state.json", [])
    if isinstance(orders, list):
        for o in orders:
            if not isinstance(o, dict):
                continue
            if o.get("status") in ("FILLED", "PARTIAL"):
                trades.append({
                    "time": o.get("created_at", ""),
                    "symbol": o.get("symbol", "?"),
                    "side": o.get("side", "").upper(),
                    "qty": o.get("qty", 0),
                    "price": o.get("price", 0),
                    "value": float(o.get("qty", 0)) * float(o.get("price", 0)),
                    "strategy": o.get("strategy", "unknown"),
                    "source": "orders_state",
                    "status": o.get("status"),
                    "order_id": o.get("intent_id", ""),
                })

    # 5. 数据库 trades 表
    try:
        from database import get_session, Trade
        session = get_session()
        try:
            db_trades = session.query(Trade).order_by(Trade.trade_time.desc()).limit(500).all()
            for t in db_trades:
                trades.append({
                    "time": str(t.trade_time) if t.trade_time else "",
                    "symbol": t.ticker,
                    "side": (t.side or "").upper(),
                    "qty": t.quantity,
                    "price": t.price,
                    "value": float(t.quantity or 0) * float(t.price or 0),
                    "strategy": t.strategy or "unknown",
                    "source": "database",
                    "notes": t.notes,
                })
        finally:
            session.close()
    except Exception:
        pass

    # 按时间倒序排序
    def _sort_key(t):
        ts = t.get("time") or t.get("created_at") or ""
        return ts if isinstance(ts, str) else ""
    trades.sort(key=_sort_key, reverse=True)

    return trades


@bp.route("/")
def page():
    return render_template("trades.html")


@bp.route("/api/trade_log")
def api_trade_log():
    """读取交易记录（合并所有数据源）"""
    trades = _collect_trades()
    return jsonify(_fix({"trades": trades, "total": len(trades)}))


@bp.route("/api/portfolio_history")
def api_portfolio_history():
    """从日报文件读取历史权益"""
    import glob
    history = []
    reports_dir = "signals/reports"
    if os.path.exists(reports_dir):
        for f in sorted(glob.glob(f"{reports_dir}/report_*.txt")):
            date = os.path.basename(f).replace("report_", "").replace(".txt", "")
            content = open(f).read()
            for line in content.split("\n"):
                if "权益:" in line:
                    try:
                        eq = float(line.split("$")[1].replace(",", ""))
                        history.append({"date": date, "equity": eq})
                    except:
                        pass
                    break
    return jsonify(_fix(history))


@bp.route("/api/attribution")
def api_attribution():
    """绩效归因"""
    from performance_attribution import get_stats
    try:
        report = get_stats()
        return jsonify(_fix(report))
    except Exception as e:
        return jsonify({"error": str(e)})


@bp.route("/api/stats")
def api_stats():
    """交易统计"""
    trades = _collect_trades()

    buys = [t for t in trades if t.get("side", "").upper() == "BUY"]
    sells = [t for t in trades if t.get("side", "").upper() == "SELL"]

    total_buy = sum(t.get("value", 0) for t in buys)
    total_sell = sum(t.get("value", 0) for t in sells)
    total_trades = len(trades)

    # 按股票统计
    by_symbol = {}
    for t in trades:
        sym = t.get("symbol", "?")
        if sym not in by_symbol:
            by_symbol[sym] = {"buy_count": 0, "sell_count": 0, "buy_value": 0, "sell_value": 0}
        if t.get("side", "").upper() == "BUY":
            by_symbol[sym]["buy_count"] += 1
            by_symbol[sym]["buy_value"] += t.get("value", 0)
        else:
            by_symbol[sym]["sell_count"] += 1
            by_symbol[sym]["sell_value"] += t.get("value", 0)

    # 按策略统计
    by_strategy = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        if s not in by_strategy:
            by_strategy[s] = 0
        by_strategy[s] += 1

    return jsonify(_fix({
        "total_trades": total_trades,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_buy_volume": total_buy,
        "total_sell_volume": total_sell,
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
    }))
