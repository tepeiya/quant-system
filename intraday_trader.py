"""
日内交易执行器 v3 — 独立于主策略
================================
- 云端止损单（Alpaca StopLossOrder，即时生效）
- 移动止损（可选，默认关闭，每15分钟检查）
- 固定止盈止损

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
INTRA_HIGH_FILE = "data_cache/intraday_highs.json"
CAPITAL_RATIO = float(os.environ.get("INTRADAY_CAP_RATIO", "0.20"))


def load_intraday_config() -> dict:
    path = "config/intraday_config.json"
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except:
            pass
    return {}


def get_alpaca(strategy: str = "intraday"):
    from broker_manager import BrokerManager, load_config
    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id(strategy)
    cfg = load_config().get(broker_id, {})
    if not cfg.get("enabled", False):
        logger.error(f"券商 {broker_id} 未启用")
        return None
    from alpaca.trading.client import TradingClient
    key_name = cfg.get("env_key_id", "ALPACA_API_KEY_ID")
    sec_name = cfg.get("env_secret", "ALPACA_SECRET_KEY")
    try:
        from broker_keys import get_key_unified
        key = get_key_unified(key_name)
        secret = get_key_unified(sec_name)
    except:
        key = os.environ.get(key_name, "")
        secret = os.environ.get(sec_name, "")
    if not key or not secret:
        logger.error(f"Key未配置: {key_name}/{sec_name}")
        return None
    return TradingClient(key, secret, paper=cfg.get("paper", True))


def load_signal() -> dict:
    try:
        if os.path.exists(SIGNAL_FILE):
            with open(SIGNAL_FILE) as f:
                return json.load(f)
    except:
        pass
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


def load_highs() -> dict:
    try:
        if os.path.exists(INTRA_HIGH_FILE):
            with open(INTRA_HIGH_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}


def save_highs(highs: dict):
    try:
        os.makedirs("data_cache", exist_ok=True)
        with open(INTRA_HIGH_FILE, "w") as f:
            json.dump(highs, f, indent=2)
    except:
        pass


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


def place_cloud_stop(client, sym: str, qty: int, stop_price: float):
    """提交云端止损单（Alpaca StopLossOrder）"""
    from alpaca.trading.requests import StopLossOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    try:
        order = StopLossOrderRequest(
            symbol=sym, qty=qty, side=OrderSide.SELL,
            stop_price=round(stop_price, 2),
            time_in_force=TimeInForce.DAY)
        client.submit_order(order)
        logger.info(f"  云端止损单: {sym} @ ${stop_price:.2f}")
        return True
    except Exception as e:
        logger.error(f"  云端止损单失败 {sym}: {str(e)[:80]}")
        return False


def cancel_cloud_stops(client, sym: str = None):
    """取消云端止损单"""
    from alpaca.trading.requests import StopLossOrderRequest
    try:
        orders = client.get_orders(status='OPEN')
        for o in orders:
            if o.order_type == 'stop' or o.order_type == 'stop_limit':
                if sym is None or o.symbol == sym:
                    client.cancel_order_by_id(o.id)
    except:
        pass


def check_stop_loss():
    """检查持仓：云端止损+移动止损+ATR自适应止盈止损"""
    client = get_alpaca()
    if not client:
        return

    cfg = load_intraday_config()
    # 从信号中读取个股的ATR自适应止损止盈
    signal = load_signal()
    candidate_map = {}
    for c in signal.get("candidates", []):
        candidate_map[c["ticker"]] = c

    # 默认值（当信号中没有时回退）
    default_stop = 1.5
    default_tp = 2.5
    trailing_enabled = cfg.get("trailing_stop_enabled", False)

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    positions = get_positions(client)
    if not positions:
        return

    highs = load_highs()
    closed = []

    for sym, pos in positions.items():
        entry = pos["avg_entry"]
        cur = pos["current_price"]
        pnl = pos["pnl_pct"]

        # 获取个股的ATR自适应止损止盈
        ci = candidate_map.get(sym, {})
        sl_pct = float(ci.get("stop_loss_pct", default_stop))
        tp_pct = float(ci.get("take_profit_pct", default_tp))
        trail_pct = float(cfg.get("trailing_stop_atr_multiple", 1.0)) * float(ci.get("atr_pct", 1.0))

        # 更新最高价（用于移动止损）
        if trailing_enabled:
            old_high = highs.get(sym, entry)
            if cur > old_high:
                highs[sym] = cur

        # 止盈（ATR自适应）
        if pnl >= tp_pct:
            logger.info(f"  [止盈] {sym} {pnl:+.2f}% >= {tp_pct}% (ATR自适应)")
            try:
                cancel_cloud_stops(client, sym)
                client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY))
                closed.append({"symbol": sym, "reason": "take_profit", "pnl_pct": pnl})
                logger.info(f"    止盈卖出 {sym}")
            except Exception as e:
                logger.error(f"    止盈失败: {e}")
            continue

        # 移动止损（从最高点回落，ATR自适应）
        if trailing_enabled:
            peak = highs.get(sym, entry)
            if peak > entry and cur < peak * (1 - trail_pct / 100):
                logger.info(f"  [移动止损] {sym} {pnl:+.2f}% 从最高{peak:.2f}回落{(peak-cur)/peak*100:.2f}% (ATR: {trail_pct:.1f}%)")
                try:
                    cancel_cloud_stops(client, sym)
                    client.submit_order(MarketOrderRequest(
                        symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY))
                    closed.append({"symbol": sym, "reason": "trailing_stop", "pnl_pct": pnl})
                    logger.info(f"    移动止损卖出 {sym}")
                except Exception as e:
                    logger.error(f"    移动止损失败: {e}")
                continue

        # 固定止损（ATR自适应，由云端止损单保障）
        if pnl <= -sl_pct:
            logger.info(f"  [止损补单] {sym} {pnl:+.2f}% <= -{sl_pct}% (ATR自适应)")
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY))
                closed.append({"symbol": sym, "reason": "stop_loss", "pnl_pct": pnl})
                logger.info(f"    止损卖出 {sym}")
            except Exception as e:
                logger.error(f"    止损失败: {e}")

    # 保存最高价
    if trailing_enabled:
        save_highs(highs)

    if closed:
        trade_log = load_trade_log()
        trade_log["trades"].append({
            "time": str(datetime.now()),
            "action": "stop_check",
            "closed": closed,
        })
        save_trade_log(trade_log)
        logger.info(f"止盈止损完成: {len(closed)}笔")


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

    cfg = load_intraday_config()
    max_pos = int(cfg.get("max_positions", 5))

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    acct = client.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    allocated = min(equity * CAPITAL_RATIO, cash)  # 日内分配资金，不超过可用现金

    positions = get_positions(client)
    trade_log = load_trade_log()
    trades = []

    logger.info(f"权益: ${equity:.2f}, 日内分配: ${allocated:.2f} ({CAPITAL_RATIO*100:.0f}%)")
    logger.info(f"当前持仓: {len(positions)} 只 (上限{max_pos})")

    check_stop_loss()
    positions = get_positions(client)

    # 如果已达最大持仓数，不再买入
    if len(positions) >= max_pos:
        logger.info(f"  持仓已达上限({max_pos}只)，跳过本次买入")
        return

    # 剩余可买仓位
    remaining_slots = max_pos - len(positions)
    candidates = candidates[:remaining_slots]
    logger.info(f"  可买: {len(candidates)}/{remaining_slots}只")

    # 剩余资金在候选股之间平分
    per_target = allocated / max(len(candidates), 1)
    remaining_cash = allocated

    for c in candidates:
        sym = c["ticker"]
        if sym in positions:
            logger.info(f"  已有 {sym}，跳过")
            continue
        price = c.get("price", 0)
        if price <= 0:
            continue

        qty = int(min(per_target, remaining_cash) / price)
        if qty <= 0:
            qty = 1
        cost = qty * price
        if cost > remaining_cash:
            qty = int(remaining_cash / price)
            if qty <= 0:
                continue
            cost = qty * price

        if qty > 0 and auto:
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=qty, side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY))
                remaining_cash -= cost
                logger.info(f"  买入 {sym} x{qty} @ ${price:.2f} (已用${allocated-remaining_cash:.0f}/{allocated:.0f})")

                # 买入后立即提交云端止损单
                sl_pct = float(c.get("stop_loss_pct", 1.5))
                stop_price = price * (1 - sl_pct / 100)
                place_cloud_stop(client, sym, qty, stop_price)
            except Exception as e:
                logger.error(f"  买入 {sym} 失败: {str(e)[:80]}")
                continue
        else:
            logger.info(f"  [预览] 买入 {sym} x{qty} @ ${price:.2f}")
        trades.append({"symbol": sym, "side": "BUY", "qty": qty, "price": round(price, 2), "auto": auto})

    logger.info(f"执行完成: {len(trades)}笔 (剩余资金${remaining_cash:.0f})")

    if trades:
        trade_log["trades"].append({"time": str(datetime.now()), "action": "scan", "trades": trades})
        save_trade_log(trade_log)
        logger.info(f"执行完成: {len(trades)}笔")


def close_all(auto: bool = False):
    """强制清仓"""
    client = get_alpaca()
    if not client:
        return
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    positions = get_positions(client)
    if not positions:
        logger.info("无持仓需清仓")
        return

    # 先取消所有云端止损单
    cancel_cloud_stops(client)

    trades = []
    for sym, pos in positions.items():
        if auto:
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=pos["qty"], side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY))
                logger.info(f"  清仓 {sym} x{pos['qty']}")
            except Exception as e:
                logger.error(f"  清仓 {sym} 失败: {str(e)[:80]}")
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
