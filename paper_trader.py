"""
Alpaca 纸交易执行器 v2
==================
功能：读取信号 → 对比当前持仓 → 自动执行调仓

v2 升级：
  1. 正确对比持仓和信号，只买卖差额
  2. 按等权分配资金（每只1/8仓位）
  3. 自动处理碎股
  4. 记录每笔交易到日志

用法：
  python3 paper_trader.py                       # 手动模式
  python3 paper_trader.py --auto                # 自动执行调仓
  python3 paper_trader.py --status              # 查看持仓和PnL
"""

import os
import sys
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quant.paper")

SIGNALS_DIR = "signals"
TRADE_LOG = "signals/trade_log.json"


def get_alpaca(strategy: str = "conservative"):
    """获取默认券商客户端（按策略绑定券商）"""
    from broker_manager import BrokerManager, load_config

    bm = BrokerManager()
    broker_id = bm.get_strategy_broker_id(strategy)
    cfg = load_config().get(broker_id, {})

    if cfg.get("type") != "alpaca":
        logger.error(f"策略 {strategy} 绑定券商 {broker_id} 非 Alpaca")
        sys.exit(1)

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
        logger.error(f"请设置 {key_name} 和 {sec_name}")
        sys.exit(1)
    paper = cfg.get("paper", True)
    return TradingClient(key, secret, paper=paper)


def periodic_rebalance(auto: bool = False):
    """
    月度再平衡：不改变选股，只调整现有持仓到等权目标。
    确保因子暴露不因涨跌偏离。
    """
    client = get_alpaca()
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    # 读取最新信号中的候选列表（作为目标池）
    import glob
    files = sorted(glob.glob(f"{SIGNALS_DIR}/signal_*.json"))
    target_symbols = []
    current_prices = {}
    if files:
        with open(files[-1]) as f:
            signal = json.load(f)
            for c in signal.get("buy_candidates", []):
                target_symbols.append(c["ticker"])
                if "price" in c:
                    current_prices[c["ticker"]] = c["price"]

    if not target_symbols:
        # 如果没有信号，用当前持仓作为目标
        target_symbols = [p.symbol for p in client.get_all_positions()]

    if not target_symbols:
        print("无目标持仓，跳过再平衡")
        return

    # 获取当前持仓
    positions = {p.symbol: int(p.qty) for p in client.get_all_positions()}
    acct = client.get_account()
    portfolio_value = float(acct.equity)

    # 获取各股最新价格（从Alpaca实时）
    import requests as _req
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    for sym in target_symbols:
        if sym not in current_prices or current_prices[sym] <= 0:
            try:
                r = _req.get(f"https://data.alpaca.markets/v2/stocks/{sym}/trades/latest",
                             auth=(KEY, SECRET), timeout=5)
                if r.status_code == 200:
                    current_prices[sym] = float(r.json().get("trade", {}).get("p", 0))
            except:
                continue

    # 计算等权目标
    n_positions = len(target_symbols)
    if n_positions == 0:
        return
    target_value = portfolio_value * 0.90 / n_positions  # 留10%现金

    orders = []
    for sym in target_symbols:
        price = current_prices.get(sym, 0)
        if price <= 0:
            continue
        target_qty = max(1, int(target_value / max(price, 1)))
        current_qty = positions.get(sym, 0)
        diff = target_qty - current_qty

        if abs(diff) < 1:
            continue
        if diff > 0:
            orders.append((sym, diff, "BUY"))
        else:
            orders.append((sym, abs(diff), "SELL"))

    if not orders:
        print("✅ 无需再平衡，持仓已在目标附近")
        return

    print(f"\n📋 月度再平衡计划 ({len(orders)}笔):")
    for sym, qty, side in orders:
        print(f"  {'🟢' if side=='BUY' else '🔴'} {side:>4} {sym:>6} x{qty:>4} @ ${current_prices.get(sym,0):>7.2f}")

    if auto:
        print("\n⚡ 执行再平衡...")
        for sym, qty, side in orders:
            try:
                order = client.submit_order(MarketOrderRequest(
                    symbol=sym, qty=qty,
                    side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                ))
                print(f"  ✅ {side} {sym} x{qty}")
                try:
                    from portfolio_tracker import record_trade
                    record_trade(sym, side, qty, current_prices.get(sym, 0))
                except:
                    pass
            except Exception as e:
                print(f"  ❌ {side} {sym}: {str(e)[:60]}")
    else:
        print(f"\n  执行: python3 paper_trader.py --rebalance --auto")


def show_status():
    """显示账户状态和持仓"""
    client = get_alpaca()
    acct = client.get_account()

    print(f"\n{'='*55}")
    print(f"  Alpaca 纸交易 - 账户状态")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")
    print(f"现金:      ${float(acct.cash):>10,.2f}")
    print(f"持仓市值:  ${float(acct.portfolio_value) - float(acct.cash):>10,.2f}")
    print(f"总权益:    ${float(acct.equity):>10,.2f}")
    print(f"购买力:    ${float(acct.buying_power):>10,.2f}")
    print(f"今日PnL:   ${float(acct.equity) - float(acct.last_equity):>+10,.2f}")

    positions = client.get_all_positions()
    if positions:
        print(f"\n📋 当前持仓")
        print(f"  {'股票':>6} {'数量':>6} {'均价':>8} {'现价':>8} {'市值':>10} {'PnL%':>8}")
        print(f"  {'-'*50}")
        for p in positions:
            pnl = float(p.unrealized_pl_pct) * 100
            print(f"  {p.symbol:>6} {int(p.qty):>6} ${float(p.avg_entry_price):>7.2f} "
                  f"${float(p.current_price):>7.2f} ${float(p.market_value):>9,.0f} {pnl:>+7.2f}%")
    else:
        print(f"\n📋 当前持仓: 空仓")

    # 今日交易
    from alpaca.trading.requests import GetOrdersRequest
    orders = client.get_orders(GetOrdersRequest(limit=10, status="closed"))
    today = datetime.now().strftime("%Y-%m-%d")
    today_orders = [o for o in orders if o.filled_at and o.filled_at.startswith(today)]
    if today_orders:
        print(f"\n📝 今日交易:")
        for o in today_orders:
            print(f"  {o.side:>4} {o.symbol:>6} x{o.qty:>4} @ ${float(o.filled_avg_price):>7.2f} "
                  f"({o.filled_at[11:16]})")


def rebalance(auto: bool = False):
    """
    核心调仓逻辑：
    1. 读取最新信号
    2. 获取当前持仓
    3. 计算目标持仓（等权配置信号推荐的股票）
    4. 生成买卖指令
    5. 执行
    """
    client = get_alpaca()
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    # 1. 读取信号
    import glob
    files = sorted(glob.glob(f"{SIGNALS_DIR}/signal_*.json"))
    if not files:
        logger.error("无信号文件，先跑 python3 daily_signal.py")
        return
    with open(files[-1]) as f:
        signal = json.load(f)

    date = signal.get("date", "?")
    candidates = signal.get("buy_candidates", [])
    market = signal.get("market", {})
    trend = market.get("action", "")

    print(f"\n{'='*55}")
    print(f"  策略调仓: {date}")
    print(f"  大盘: {market.get('trend','?')} → {trend}")
    print(f"{'='*55}")

    # 大盘不允许买入
    if "空仓" in trend or "减仓" in trend:
        print(f"\n⚠️ 大盘风险，不清仓但也不买入")
        # 不清仓（保留现有持仓），仅卖出止损票
        return

    # 2. 当前持仓
    positions = {p.symbol: int(p.qty) for p in client.get_all_positions()}

    # ⛔ 防重复：今天已交易过的股票不再交易
    today = datetime.now().strftime("%Y-%m-%d")
    today_traded = set()
    try:
        from alpaca.trading.requests import GetOrdersRequest
        recent_orders = client.get_orders(GetOrdersRequest(limit=50, status="closed"))
        for o in recent_orders:
            if o.filled_at and o.filled_at.startswith(today) and o.symbol:
                today_traded.add(o.symbol)
        if today_traded:
            logger.info(f"今日已交易: {today_traded}，跳过重复")
    except:
        pass

    # 4. 预先获取价格
    prices = {}
    for sym in [c["ticker"] for c in candidates if c["ticker"] not in today_traded]:
        for c in candidates:
            if c["ticker"] == sym:
                prices[sym] = c.get("price", 0)
                break
        if sym not in prices:
            prices[sym] = 0

    # 价格过滤（避免高价股买不起导致空仓）
    from system_config import load as _load_cfg
    cfgv = _load_cfg()
    max_share_price = float(cfgv.get("max_share_price", 300))
    primary = [c["ticker"] for c in candidates[:8] if c["ticker"] not in today_traded and prices.get(c["ticker"], 0) > 0 and prices.get(c["ticker"], 0) <= max_share_price]
    # 候补池（Top9-15）用于填满仓位
    backup = [c["ticker"] for c in candidates[8:15] if c["ticker"] not in today_traded and prices.get(c["ticker"], 0) > 0 and prices.get(c["ticker"], 0) <= max_share_price]

    target_symbols = primary[:8]
    # 补位：最多补到8只
    for s in backup:
        if len(target_symbols) >= 8:
            break
        if s not in target_symbols:
            target_symbols.append(s)

    if not target_symbols:
        print("\n无可买入候选（可能都超出价格上限）")
        return

    # 获取激进策略持仓，避免重复买入
    try:
        from paper_trader_momentum import get_alpaca as get_momentum_alpaca, get_current_positions as get_mom_positions
        mom_client = get_momentum_alpaca(strategy="momentum")
        if mom_client:
            mom_held = set(get_mom_positions(mom_client).keys())
            if mom_held:
                logger.info(f"激进策略已有持仓: {mom_held}")
                target_symbols = [s for s in target_symbols if s not in mom_held]
                logger.info(f"去重后保守目标: {len(target_symbols)}只: {', '.join(target_symbols)}")
    except Exception as e:
        logger.debug(f"获取激进持仓失败: {e}")
    
    # 5. 计算等权目标仓位
    acct = client.get_account()
    portfolio_value = float(acct.equity)
    # 根据资金规模调整：小额账户最小买入1股，大额按比例
    if portfolio_value <= 5000:
        # 迷你账户：等权分配，每只买1~2股
        target_shares = {}
        for sym in target_symbols[:4]:
            price = prices.get(sym, 0)
            if not price or price <= 0:
                continue
            qty = max(1, int(portfolio_value * 0.22 / max(price, 1)))
            target_shares[sym] = qty
        logger.info(f"迷你账户模式: ${portfolio_value:.0f}, 目标{len(target_shares)}只")
    else:
        # 标准账户：按15%上限等权分配
        target_pct = 1.0 / len(target_symbols)
        max_pct = 0.15
        for sym in target_symbols:
            price = prices.get(sym)
            if not price or price <= 0:
                continue
            target_value = portfolio_value * min(target_pct, max_pct)
            target_shares[sym] = max(1, int(target_value / max(price, 1)))

    # 5. 生成调仓指令
    orders_to_place = []

    # 卖出（不再持有的）
    total_value = 0
    for sym, qty in positions.items():
        if sym not in target_shares:
            orders_to_place.append((sym, qty, "SELL"))
        else:
            # 调整股数
            target = target_shares[sym]
            if qty > target:
                orders_to_place.append((sym, qty - target, "SELL"))
            elif qty < target:
                orders_to_place.append((sym, target - qty, "BUY"))

    # 买入新票
    for sym, qty in target_shares.items():
        if sym not in positions or positions[sym] == 0:
            orders_to_place.append((sym, qty, "BUY"))

    if not orders_to_place:
        print("\n✅ 无需调仓，当前持仓与信号一致")
        return

    # 6. 展示
    print(f"\n📋 调仓计划:")
    for sym, qty, side in orders_to_place:
        emoji = "🟢" if side == "BUY" else "🔴"
        print(f"  {emoji} {side:>4} {sym:>6} x{qty:>4}")

    # 7. 执行
    if auto:
        print(f"\n⚡ 自动执行中...")
        for sym, qty, side in orders_to_place:
            try:
                # 获取最新价格
                current_price = prices.get(sym, 0)
                if side == "BUY" and current_price > 0:
                    # 买价保护：限价单，比当前价高3%（允许合理滑点，防止极端价格）
                    limit_price = round(current_price * 1.03, 2)
                    from alpaca.trading.requests import LimitOrderRequest
                    order = client.submit_order(LimitOrderRequest(
                        symbol=sym, qty=qty, side=OrderSide.BUY,
                        limit_price=limit_price,
                        time_in_force=TimeInForce.DAY,
                    ))
                else:
                    order = client.submit_order(MarketOrderRequest(
                        symbol=sym, qty=qty,
                        side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                    ))
                print(f"  ✅ {side} {sym} x{qty}")
                try:
                    from portfolio_tracker import record_trade
                    record_trade(sym, side, qty, current_price)
                except Exception:
                    pass
            except Exception as e:
                print(f"  ❌ {side} {sym}: {str(e)[:60]}")
        
        # 调仓完成后同步持仓
        try:
            from portfolio_tracker import sync_from_alpaca
            sync_from_alpaca()
        except:
            pass
    
    else:
        print(f"\n⚠️  手动模式 - 预览")
        print(f"   执行: python3 paper_trader.py --auto")


def close_all():
    """平所有仓位"""
    client = get_alpaca()
    positions = client.get_all_positions()
    if not positions:
        print("空仓")
        return
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    for p in positions:
        try:
            order = client.submit_order(MarketOrderRequest(
                symbol=p.symbol, qty=int(p.qty),
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            ))
            print(f"  ✅ {p.symbol}")
        except Exception as e:
            print(f"  ❌ {p.symbol}: {str(e)[:60]}")
    print("全部平仓完成")


def show_log():
    """查看最近交易记录"""
    if not os.path.exists(TRADE_LOG):
        print("暂无交易记录")
        return
    with open(TRADE_LOG) as f:
        log = json.load(f)
    print(f"\n📝 最近交易 (共{len(log)}笔)")
    print(f"  {'时间':<20} {'操作':>4} {'股票':>6} {'数量':>6}")
    print(f"  {'-'*40}")
    for entry in log[-20:]:
        t = entry.get("time", "?")[11:19]
        print(f"  {t:<20} {entry['side']:>4} {entry['symbol']:>6} {entry['qty']:>6}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--status" in args:
        show_status()
    elif "--close-all" in args:
        close_all()
    elif "--log" in args:
        show_log()
    elif "--rebalance" in args:
        auto = "--auto" in args
        periodic_rebalance(auto=auto)
    else:
        auto = "--auto" in args
        if auto:
            rebalance(auto=True)
        else:
            rebalance(auto=False)
