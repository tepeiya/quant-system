"""
配对交易自动执行器 v1
====================
功能：自动做空+做多，价差回归自动平仓

用法：
  python3 pairs_executor.py --scan      # 扫描配对信号
  python3 pairs_executor.py --execute   # 自动执行
  python3 pairs_executor.py --status    # 持仓状态
  python3 pairs_executor.py --close-all # 平仓所有
"""

import os, sys, json, logging, time
from datetime import datetime, timedelta
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("quant.pairs")

# 配置
MAX_PAIRS = 3          # 最多同时持有配对数
MAX_DAYS = 30          # 最大持仓天数
ZSCORE_ENTRY = 1.5     # 开仓Z-score阈值
ZSCORE_EXIT = 0.3      # 平仓Z-score阈值
ZSCORE_STOP = 3.0      # 止损Z-score阈值
PER_PAIR_PCT = 0.20    # 单配对资金占比


def get_alpaca():
    """获取默认券商客户端（当前配对执行器优先支持 Alpaca）"""
    from broker_manager import get_default_broker_id, load_config
    default_id = get_default_broker_id()
    cfg = load_config().get(default_id, {})
    if cfg.get("type") != "alpaca":
        raise RuntimeError(f"当前默认券商是 {default_id}，pairs_executor 暂仅支持 Alpaca 自动执行")

    from alpaca.trading.client import TradingClient
    key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
    secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
    return TradingClient(key, secret, paper=cfg.get("paper", True))


def get_positions():
    """获取当前持仓（含做空仓位）"""
    client = get_alpaca()
    positions = {}
    try:
        for p in client.get_all_positions():
            positions[p.symbol] = {
                "qty": int(p.qty),
                "market_value": float(p.market_value),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "pnl_pct": float(p.unrealized_plpc) * 100,
                "pnl": float(p.unrealized_pl),
            }
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
    return positions


def scan_signals(cache: dict = None):
    """扫描配对信号，返回可执行的配对"""
    if cache is None:
        from data_prod import load_price_cache
        cache = load_price_cache()

    from pairs_trading import generate_pair_signals
    signals = generate_pair_signals(cache)

    # 只保留需要开仓的信号
    executable = []
    for s in signals:
        if s.get("status") == "open":
            executable.append(s)

    return executable


def execute_pairs_auto(cache: dict = None):
    """
    自动执行配对交易——自动做空+做多
    
    逻辑：
      1. 扫描配对信号
      2. 对Z-score>阈值的配对：
         - 做空强势股（SELL）
         - 做多弱势股（BUY）
      3. 记录开仓信息
    """
    if cache is None:
        from data_prod import load_price_cache
        cache = load_price_cache()

    # 获取当前持仓
    positions = get_positions()
    logger.info(f"当前持仓股票数: {len(positions)}")

    # 获取账户信息
    client = get_alpaca()
    try:
        acct = client.get_account()
        equity = float(acct.equity)
        logger.info(f"账户权益: ${equity:.2f}")
    except Exception as e:
        logger.error(f"获取账户失败: {e}")
        return

    # 计算每对可用资金
    per_pair = equity * PER_PAIR_PCT
    logger.info(f"单配对资金: ${per_pair:.2f}")

    # 扫描信号
    from pairs_trading import generate_pair_signals
    signals = generate_pair_signals(cache)

    # 过滤信号
    active = [s for s in signals if s.get("status") == "open" and abs(s.get("zscore", 0)) >= ZSCORE_ENTRY]
    active = sorted(active, key=lambda x: abs(x.get("zscore", 0)), reverse=True)

    logger.info(f"可执行配对: {len(active)}")

    if not active:
        print("\n✅ 没有需要执行的配对信号")
        return

    # 平仓Z-score已回归的配对
    closed = [s for s in signals if s.get("status") == "close" and abs(s.get("zscore", 0)) <= ZSCORE_EXIT]
    if closed:
        logger.info(f"需要平仓: {len(closed)}对")
        for s in closed:
            pair = s.get("pair", "?")
            z = s.get("zscore", 0)
            logger.info(f"  平仓 {pair} (z={z:.2f})")

    # 执行开仓
    taken = 0
    for s in active[:MAX_PAIRS]:
        pair = s.get("pair", "")
        parts = pair.split("/")
        if len(parts) != 2:
            continue

        ticker_a, ticker_b = parts[0], parts[1]
        zscore = s.get("zscore", 0)
        hedge = s.get("hedge_ratio", 1.0)

        # 确定做空/做多方向
        # zscore>0: A比B强 → 做空A，做多B
        if zscore > 0:
            short_ticker, long_ticker = ticker_a, ticker_b
        else:
            short_ticker, long_ticker = ticker_b, ticker_a

        # 计算数量
        price_data_a = cache.get(short_ticker)
        price_data_b = cache.get(long_ticker)
        if price_data_a is None or price_data_b is None:
            continue
        price_a = float(price_data_a["Close"].iloc[-1])
        price_b = float(price_data_b["Close"].iloc[-1])
        if price_a <= 0 or price_b <= 0:
            continue

        # 做空short_ticker + 做多long_ticker，等额对冲
        short_qty = max(1, int(per_pair * 0.5 / price_a))
        long_qty = max(1, int(per_pair * 0.5 / price_b))

        # 检查是否已有持仓
        already_short = any(t in short_ticker for t in positions.keys()) if positions.get(short_ticker) else False

        if already_short:
            logger.info(f"  跳过 {short_ticker} → 已有持仓")
            continue

        logger.info(f"\n  🔴 做空 {short_ticker} x{short_qty} @ ${price_a:.2f}")
        logger.info(f"  🟢 做多 {long_ticker} x{long_qty} @ ${price_b:.2f}")
        logger.info(f"  z-score: {zscore:.2f} | 对冲比: {hedge:.2f}")

        # 执行订单
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        try:
            order_short = client.submit_order(MarketOrderRequest(
                symbol=short_ticker, qty=short_qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            ))
            logger.info(f"  ✅ 做空 {short_ticker} 成功: {order_short.id}")
        except Exception as e:
            logger.error(f"  ❌ 做空 {short_ticker} 失败: {str(e)[:60]}")
            continue

        try:
            time.sleep(0.5)
            order_long = client.submit_order(MarketOrderRequest(
                symbol=long_ticker, qty=long_qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            ))
            logger.info(f"  ✅ 做多 {long_ticker} 成功: {order_long.id}")
        except Exception as e:
            logger.error(f"  ❌ 做多 {long_ticker} 失败: {str(e)[:60]}")
            continue

        taken += 1

    logger.info(f"\n完成: 开仓{taken}对")
    return taken


def close_all():
    """平仓所有配对——买入还券+卖出股票"""
    client = get_alpaca()
    positions = get_positions()
    if not positions:
        logger.info("无持仓需要平仓")
        return

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    logger.info(f"\n平仓所有持仓 ({len(positions)}只):")
    for sym, pos in positions.items():
        qty = abs(pos["qty"])
        side = OrderSide.BUY if pos["qty"] < 0 else OrderSide.SELL  # 做空→买入还券, 做多→卖出
        try:
            client.submit_order(MarketOrderRequest(
                symbol=sym, qty=qty,
                side=side, time_in_force=TimeInForce.DAY,
            ))
            logger.info(f"  ✅ {'买入' if side==OrderSide.BUY else '卖出'} {sym} x{qty}")
        except Exception as e:
            logger.error(f"  ❌ {sym}: {str(e)[:60]}")


def show_status():
    """显示配对交易状态"""
    positions = get_positions()
    print(f"\n{'='*55}")
    print(f"  🔗 配对交易状态")
    print(f"{'='*55}")
    print()
    if not positions:
        print("  📭 当前无配对持仓")
    else:
        # 找到做空仓位（配对交易标志）
        shorts = {s: p for s, p in positions.items() if p["qty"] < 0}
        longs = {s: p for s, p in positions.items() if p["qty"] > 0}
        if shorts:
            print(f"  做空: {len(shorts)}只")
            for s, p in shorts.items():
                print(f"    🔴 {s} x{abs(p['qty'])}  ${p['avg_entry']:.2f}→${p['current_price']:.2f}  {p['pnl_pct']:+.2f}%")
        if longs:
            print(f"  做多: {len(longs)}只")
            for s, p in longs.items():
                print(f"    🟢 {s} x{p['qty']}  ${p['avg_entry']:.2f}→${p['current_price']:.2f}  {p['pnl_pct']:+.2f}%")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--scan" in args:
        from data_prod import load_price_cache
        signals = scan_signals(load_price_cache())
        print(f"\n信号: {len(signals)}个可执行配对")
        for s in signals[:5]:
            print(f"  {s.get('pair')}: z={s.get('zscore',0):.2f}")
    elif "--execute" in args:
        from data_prod import load_price_cache
        execute_pairs_auto(load_price_cache())
    elif "--status" in args:
        show_status()
    elif "--close-all" in args:
        close_all()
    else:
        print(__doc__)
