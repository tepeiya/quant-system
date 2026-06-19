"""
日内交易执行器 — 独立于主策略
================================
- 根据信号买入
- 动态止盈止损（从config读取）
- 收盘前强制清仓
- 盘中止损检查

用法：
  python3 intraday_trader.py                 查看状态
  python3 intraday_trader.py --auto          自动执行
  python3 intraday_trader.py --close-all     强制清仓
  python3 intraday_trader.py --check-stop    检查止损
"""

import os, sys, json, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INTRADAY] %(message)s")
logger = logging.getLogger("quant.intraday_trader")

SIGNAL_FILE = "signals/intraday_signal.json"
TRADE_LOG = "signals/intraday_trades.json"
CONFIG_FILE = "config/intraday_config.json"

CAPITAL_RATIO = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))


def get_alpaca(strategy: str = "intraday"):
    from broker_manager import BrokerManager, load_config
    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id(strategy)
    cfg = load_config().get(broker_id, {})
    if not cfg.get("enabled", False):
        logger.error(f"策略 {strategy} 绑定的券商 {broker_id} 未启用")
        return None
    from alpaca.trading.client import TradingClient
    key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
    secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
    if not key or not secret:
        logger.error(f"环境变量未设置: {cfg.get('env_key_id')} / {cfg.get('env_secret')}")
        return None
    return TradingClient(key, secret, paper=cfg.get("paper", True))


def load_intraday_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}


def load_signal() -> dict:
    try:
        if os.path.exists(SIGNAL_FILE):
            with open(SIGNAL_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"读取信号失败: {e}")
    return {}


def load_trade_log() -> dict:
    try:
        if os.path.exists(TRADE_LOG):
            with open(TRADE_LOG) as f:
                return json.load(f)
    except:
        pass
    return {"trades": []}


def save_trade_log(log: dict):
    try:
        os.makedirs("signals", exist_ok=True)
        with open(TRADE_LOG, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        logger.error(f"保存交易日志失败: {e}")


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
                    "market_value": float(p.market_value),
                }
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
    return positions


def check_stop_loss():
    """检查持仓是否需要止盈止损"""
    client = get_alpaca()
    if not client:
        return

    cfg = load_intraday_config()
    stop_loss_pct = float(cfg.get("stop_loss_pct", 1.5))
    take_profit_pct = float(cfg.get("take_profit_pct", 2.5))
    trailing_stop_pct = float(cfg.get("trailing_stop_pct", 1.0))
    
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    positions = get_positions(client)
    if not positions:
        return

    # 获取最新价格
    import requests as _req
    from broker_manager import load_config, get_default_broker_id
    broker_cfg = load_config().get(get_default_broker_id(), {})
    key = os.environ.get(broker_cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
    secret = os.environ.get(broker_cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
    
    closed = []
    for sym, pos in positions.items():
        entry = pos["avg_entry"]
        pnl = pos["pnl_pct"]
        
        # 止盈
        if pnl >= take_profit_pct:
            logger.info(f"  [止盈] {sym} {pnl:+.2f}% >= {take_profit_pct}%")
            if client:
                try:
                    client.submit_order(MarketOrderRequest(
                        symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY))
                    closed.append({"symbol": sym, "qty": pos["qty"], "reason": "take_profit", "pnl_pct": pnl})
                    logger.info(f"    止盈卖出 {sym} x{pos['qty']}")
                except Exception as e:
                    logger.error(f"    止盈失败: {e}")
            continue
        
        # 止损
        if pnl <= -stop_loss_pct:
            logger.info(f"  [止损] {sym} {pnl:+.2f}% <= -{stop_loss_pct}%")
            if client:
                try:
                    client.submit_order(MarketOrderRequest(
                        symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY))
                    closed.append({"symbol": sym, "qty": pos["qty"], "reason": "stop_loss", "pnl_pct": pnl})
                    logger.info(f"    止损卖出 {sym} x{pos['qty']}")
                except Exception as e:
                    logger.error(f"    止损失败: {e}")
            continue

    if closed:
        trade_log = load_trade_log()
        trade_log["trades"].append({
            "time": str(datetime.now()),
            "action": "stop_check",
            "closed": closed,
        })
        save_trade_log(trade_log)
        logger.info(f"止盈止损检查完成: 平仓{len(closed)}笔")


def execute_intraday(auto: bool = False):
    """执行日内交易"""
    client = get_alpaca()
    if not client:
        return

    signal = load_signal()
    candidates = signal.get("candidates", [])
    if not candidates:
        logger.info("无日内信号")
        return

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

    # 先检查止盈止损
    check_stop_loss()

    # 重新获取持仓（止盈止损可能已经平仓）
    positions = get_positions(client)

    # 买入信号股
    per_target = allocated / max(len(candidates), 1)
    for c in candidates:
        sym = c["ticker"]
        if sym in positions:
            logger.info(f"  已有 {sym}，跳过")
            continue
        price = c.get("price", 0)
        if price <= 0:
            logger.warning(f"  {sym} 价格无效，跳过")
            continue
        qty = int(per_target / price)
        if qty <= 0:
            qty = 1
        cost = qty * price
        if cost > cash:
            qty = int(cash / price)
            if qty <= 0:
                logger.warning(f"  {sym} 现金不足，跳过")
                continue
            cost = qty * price
        if qty > 0:
            if auto:
                try:
                    client.submit_order(MarketOrderRequest(
                        symbol=sym, qty=qty, side=OrderSide.BUY,
                        time_in_force=TimeInForce.DAY))
                    cash -= cost
                    logger.info(f"  买入 {sym} x{qty} @ ${price:.2f}")
                except Exception as e:
                    logger.error(f"  买入 {sym} 失败: {str(e)[:100]}")
                    continue
            else:
                logger.info(f"  [预览] 买入 {sym} x{qty} @ ${price:.2f}")
            trades.append({"symbol": sym, "side": "BUY", "qty": qty, "price": round(price, 2), "auto": auto})

    if trades:
        trade_log["trades"].append({"time": str(datetime.now()), "action": "scan", "trades": trades})
        save_trade_log(trade_log)
        logger.info(f"✅ 日内执行完成: {len(trades)}笔")


def close_all(auto: bool = False):
    """强制清仓所有日内持仓"""
    client = get_alpaca()
    if not client:
        return

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    positions = get_positions(client)
    if not positions:
        logger.info("无日内持仓需清仓")
        return

    trades = []
    for sym, pos in positions.items():
        if auto:
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY))
                logger.info(f"  清仓 {sym} x{pos['qty']}")
            except Exception as e:
                logger.error(f"  清仓 {sym} 失败: {str(e)[:100]}")
                continue
        trades.append({"symbol": sym, "side": "SELL", "qty": pos["qty"]})

    trade_log = load_trade_log()
    trade_log["trades"].append({"time": str(datetime.now()), "action": "close_all", "trades": trades})
    save_trade_log(trade_log)
    logger.info(f"清仓完成: {len(trades)}笔")


if __name__ == "__main__":
    if "--auto" in sys.argv:
        execute_intraday(auto=True)
    elif "--close-all" in sys.argv:
        close_all(auto=True)
    elif "--check-stop" in sys.argv:
        check_stop_loss()
    else:
        try:
            client = get_alpaca()
            if not client:
                sys.exit(1)
            acct = client.get_account()
            positions = get_positions(client)
            print(f"\n权益: ${float(acct.equity):.2f} | 现金: ${float(acct.cash):.2f}")
            print(f"日内分配: ${float(acct.equity)*CAPITAL_RATIO:.2f} ({CAPITAL_RATIO*100:.0f}%)")
            print(f"日内持仓: {len(positions)} 只")
            for sym, p in positions.items():
                print(f"  {sym} x{p['qty']} @ ${p['current_price']:.2f} {p['pnl_pct']:+.2f}%")
            if not positions:
                print("  (空仓)")
        except Exception as e:
            print(f"获取状态失败: {e}")
