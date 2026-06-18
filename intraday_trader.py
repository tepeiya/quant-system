"""
日内交易执行器 — 独立于主策略
================================
用法：
  python3 intraday_trader.py                 查看状态
  python3 intraday_trader.py --auto          自动执行
  python3 intraday_trader.py --close-all     强制清仓
"""

import os, sys, json, logging
from datetime import datetime

logger = logging.getLogger("quant.intraday_trader")

SIGNAL_FILE = "signals/intraday_signal.json"
TRADE_LOG = "signals/intraday_trades.json"

CAPITAL_RATIO = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))


def get_alpaca(strategy: str = "intraday"):
    from broker_manager import BrokerManager, load_config
    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id(strategy)
    cfg = load_config().get(broker_id, {})
    from alpaca.trading.client import TradingClient
    key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
    secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
    return TradingClient(key, secret, paper=cfg.get("paper", True))


def load_signal() -> dict:
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            return json.load(f)
    return {}


def load_trade_log() -> dict:
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG) as f:
            return json.load(f)
    return {"trades": []}


def save_trade_log(log: dict):
    os.makedirs("signals", exist_ok=True)
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_positions(client) -> dict:
    positions = {}
    try:
        for p in client.get_all_positions():
            qty = int(float(p.qty))
            if qty > 0:
                positions[p.symbol] = {
                    "qty": qty,
                    "avg_entry": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "pnl_pct": float(p.unrealized_plpc) * 100,
                }
    except:
        pass
    return positions


def execute_intraday(auto: bool = False):
    """执行日内交易"""
    signal = load_signal()
    candidates = signal.get("candidates", [])
    if not candidates:
        logger.info("无日内信号")
        return

    client = get_alpaca()
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    acct = client.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    allocated = equity * CAPITAL_RATIO

    positions = get_positions(client)
    trade_log = load_trade_log()
    trades = []

    logger.info(f"总权益: ${equity:.2f}, 日内分配: ${allocated:.2f} ({CAPITAL_RATIO*100:.0f}%)")
    logger.info(f"当前持仓: {len(positions)} 只")

    # 收盘前强制清仓
    now = datetime.now()
    if now.hour >= 15 or (now.hour == 15 and now.minute >= 50):
        logger.info("收盘时间，强制清仓日内持仓")
        for sym, pos in positions.items():
            if auto:
                order = MarketOrderRequest(
                    symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY)
                client.submit_order(order)
            trades.append({"symbol": sym, "side": "SELL_CLOSE", "qty": pos["qty"], "auto": auto})
        if trades:
            trade_log["trades"].append({"time": str(datetime.now()), "action": "force_close", "trades": trades})
            save_trade_log(trade_log)
        return

    # 买入信号股
    per_target = allocated / len(candidates)
    for c in candidates:
        sym = c["ticker"]
        if sym in positions:
            continue
        price = c.get("price", 0)
        if price <= 0:
            continue
        qty = int(per_target / price)
        if qty <= 0:
            continue
        cost = qty * price
        if cost > cash:
            qty = int(cash / price)
            cost = qty * price
        if qty > 0 and auto:
            order = MarketOrderRequest(
                symbol=sym, qty=qty, side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY)
            client.submit_order(order)
            cash -= cost
        trades.append({"symbol": sym, "side": "BUY", "qty": qty, "price": round(price, 2), "auto": auto})
        logger.info(f"  买入 {sym} x{qty} @ ${price:.2f}")

    if trades:
        trade_log["trades"].append({"time": str(datetime.now()), "action": "scan", "trades": trades})
        save_trade_log(trade_log)
        logger.info(f"✅ 日内执行完成: {len(trades)}笔")


def close_all(auto: bool = False):
    """强制清仓所有日内持仓"""
    client = get_alpaca()
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    positions = get_positions(client)
    trades = []
    for sym, pos in positions.items():
        if auto:
            order = MarketOrderRequest(
                symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY)
            client.submit_order(order)
        trades.append({"symbol": sym, "side": "SELL", "qty": pos["qty"]})

    trade_log = load_trade_log()
    trade_log["trades"].append({"time": str(datetime.now()), "action": "manual_close", "trades": trades})
    save_trade_log(trade_log)
    logger.info(f"清仓完成: {len(trades)}笔")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [INTRADAY] %(message)s")
    if "--auto" in sys.argv:
        execute_intraday(auto=True)
    elif "--close-all" in sys.argv:
        close_all(auto=True)
    else:
        try:
            client = get_alpaca()
            acct = client.get_account()
            positions = get_positions(client)
            print(f"\n权益: ${float(acct.equity):.2f} | 现金: ${float(acct.cash):.2f}")
            print(f"日内分配: ${float(acct.equity)*CAPITAL_RATIO:.2f} ({CAPITAL_RATIO*100:.0f}%)")
            print(f"日内持仓: {len(positions)} 只")
            for sym, p in positions.items():
                print(f"  {sym} x{p['qty']} @ ${p['current_price']:.2f} {p['pnl_pct']:+.2f}%")
        except Exception as e:
            print(f"获取状态失败: {e}")
