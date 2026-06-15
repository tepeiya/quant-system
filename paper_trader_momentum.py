"""
动量激进策略执行器 — 与保守策略完全独立
======================================
独立信号文件: signals/signal_momentum.json
独立交易日志: signals/trade_log_momentum.json
独立持仓管理，互不覆盖

用法：
  python3 paper_trader_momentum.py              # 查看状态
  python3 paper_trader_momentum.py --auto       # 自动调仓
"""

import os, sys, json, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MOMENTUM] %(message)s")
logger = logging.getLogger("quant.momentum")

SIGNAL_FILE = "signals/signal_momentum.json"
TRADE_LOG = "signals/trade_log_momentum.json"


def get_alpaca():
    from broker_manager import get_default_broker_id, load_config
    default_id = get_default_broker_id()
    cfg = load_config().get(default_id, {})
    from alpaca.trading.client import TradingClient
    key_name = cfg.get("env_key_id", "ALPACA_API_KEY_ID")
    sec_name = cfg.get("env_secret", "ALPACA_SECRET_KEY")
    key = os.environ.get(key_name, "")
    secret = os.environ.get(sec_name, "")
    if not key or not secret:
        logger.error(f"请设置 {key_name} 和 {sec_name}")
        sys.exit(1)
    paper = cfg.get("paper", True)
    return TradingClient(key, secret, paper=paper)


def load_signal() -> dict:
    if not os.path.exists(SIGNAL_FILE):
        logger.warning(f"信号文件不存在: {SIGNAL_FILE}")
        return {}
    with open(SIGNAL_FILE) as f:
        return json.load(f)


def load_trade_log() -> dict:
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG) as f:
            return json.load(f)
    return {"trades": [], "last_rebalance": None}


def save_trade_log(log: dict):
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_current_positions(client) -> dict:
    """获取当前 Alpaca 持仓，返回 {symbol: qty}"""
    positions = {}
    try:
        for p in client.get_all_positions():
            sym = p.symbol
            qty = float(p.qty)
            if qty > 0:
                positions[sym] = qty
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
    return positions


def get_account_cash(client) -> float:
    try:
        acct = client.get_account()
        return float(acct.cash)
    except:
        return 0


def execute_rebalance(auto: bool = False):
    """执行动量策略调仓"""
    signal = load_signal()
    if not signal or not signal.get("tickers"):
        logger.error("无有效信号")
        return

    target_tickers = signal["tickers"]
    target_count = len(target_tickers)
    logger.info(f"目标持仓: {target_count}只: {', '.join(target_tickers)}")

    client = get_alpaca()
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    # 当前持仓
    current_pos = get_current_positions(client)
    cash = get_account_cash(client)
    logger.info(f"当前持仓: {len(current_pos)}只, 现金: ${cash:.2f}")

    # 计算总资产
    total_equity = cash
    for sym, qty in current_pos.items():
        try:
            p = client.get_latest_trade(sym)
            total_equity += qty * p.price
        except:
            pass

    target_per = total_equity / target_count
    logger.info(f"总资产: ${total_equity:.2f}, 每只目标: ${target_per:.2f}")

    trades = []
    trade_log = load_trade_log()

    # 1. 卖出不在目标池的持仓
    for sym, qty in current_pos.items():
        if sym not in target_tickers:
            try:
                if auto:
                    order = MarketOrderRequest(
                        symbol=sym, qty=qty, side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY
                    )
                    client.submit_order(order)
                trades.append({"symbol": sym, "side": "SELL", "qty": qty, "auto": auto})
                logger.info(f"  卖出 {sym} x{qty}")
            except Exception as e:
                logger.error(f"  卖出 {sym} 失败: {e}")

    # 2. 买入目标池中的股票
    for sym in target_tickers:
        current_qty = current_pos.get(sym, 0)
        current_value = 0
        if current_qty > 0:
            try:
                p = client.get_latest_trade(sym)
                current_value = current_qty * p.price
            except:
                pass

        diff = target_per - current_value
        if abs(diff) < target_per * 0.05:  # 偏差5%以内不调
            continue

        if auto:
            try:
                price = client.get_latest_trade(sym).price
                qty = int(abs(diff) / price)
                if qty <= 0:
                    continue
                if diff > 0:
                    # 买入
                    qty = min(qty, int(cash / price))
                    if qty > 0:
                        order = MarketOrderRequest(
                            symbol=sym, qty=qty, side=OrderSide.BUY,
                            time_in_force=TimeInForce.DAY
                        )
                        client.submit_order(order)
                        cash -= qty * price
                        trades.append({"symbol": sym, "side": "BUY", "qty": qty, "auto": True})
                        logger.info(f"  买入 {sym} x{qty}")
                else:
                    # 卖出多余
                    qty = min(qty, int(current_qty))
                    if qty > 0:
                        order = MarketOrderRequest(
                            symbol=sym, qty=qty, side=OrderSide.SELL,
                            time_in_force=TimeInForce.DAY
                        )
                        client.submit_order(order)
                        trades.append({"symbol": sym, "side": "SELL", "qty": qty, "auto": True})
                        logger.info(f"  卖出 {sym} x{qty}")
            except Exception as e:
                logger.error(f"  调仓 {sym} 失败: {e}")

    # 记录交易
    if trades:
        trade_log["trades"].append({
            "time": str(datetime.now()),
            "signal_date": signal.get("date"),
            "trades": trades,
        })
        trade_log["last_rebalance"] = str(datetime.now())
        save_trade_log(trade_log)
        logger.info(f"✅ 调仓完成: {len(trades)}笔交易")
    else:
        logger.info("无需调仓")


def show_status():
    """查看动量策略状态"""
    signal = load_signal()
    if not signal:
        print("⚠️ 无信号文件")
        return

    print("\n" + "=" * 55)
    print("  🚀 动量激进策略状态")
    print("=" * 55)
    print(f"  信号时间:  {signal.get('date', '-')}")
    print(f"  调仓日期:  {signal.get('rebalance_date', '-')}")
    print(f"  目标持仓:  {signal.get('count', 0)}只")
    print(f"  股票:      {', '.join(signal.get('tickers', [])[:8])}...")
    print()

    try:
        trade_log = load_trade_log()
        print(f"  上次调仓:  {trade_log.get('last_rebalance', '从未')}")
        print(f"  总交易:    {len(trade_log.get('trades', []))}次")
    except:
        pass

    try:
        client = get_alpaca()
        positions = get_current_positions(client)
        cash = get_account_cash(client)
        print(f"\n  当前持仓:  {len(positions)}只")
        print(f"  现金:      ${cash:.2f}")
        for sym, qty in sorted(positions.items())[:10]:
            try:
                p = client.get_latest_trade(sym)
                value = qty * p.price
                print(f"    {sym:6s} x{qty:4.0f}  ${value:.2f}")
            except:
                print(f"    {sym:6s} x{qty:4.0f}")
    except Exception as e:
        print(f"  获取持仓失败: {e}")
    print("=" * 55)


if __name__ == "__main__":
    if "--auto" in sys.argv:
        execute_rebalance(auto=True)
    else:
        show_status()
