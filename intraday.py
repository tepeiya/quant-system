"""
日内交易策略 — 完全独立于主策略
================================
- 盘中实时动量选股（按流动性和ATR筛选）
- 当日开仓当日平仓（收盘前强制清仓）
- 独立信号/日志/回测
- 独立资金分配
- 动态止盈止损+追踪止损

用法：
  python3 intraday.py --scan       扫描今日信号
  python3 intraday.py --backtest   回测
  python3 intraday.py --status     查看状态
"""

import os, sys, json, logging, numpy as np, pandas as pd
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INTRADAY] %(message)s")
logger = logging.getLogger("quant.intraday")

SIGNAL_FILE = "signals/intraday_signal.json"
TRADE_LOG = "signals/intraday_trades.json"
BACKTEST_FILE = "signals/intraday_backtest.json"
CONFIG_FILE = "config/intraday_config.json"
CACHE_DIR = "data_cache"

DEFAULT_CONFIG = {
    "enabled": True,
    "max_positions": 5,
    "per_position_pct": 0.18,
    "capital_pct": 0.20,
    "stop_loss_pct": 1.5,
    "take_profit_pct": 2.5,
    "trailing_stop_pct": 1.0,
    "scan_interval_minutes": 30,
    "close_time": "15:50",
    "momentum_windows": [5, 15, 30],
    "min_price": 5,
    "max_price": 500,
    "min_volume_ratio": 1.5,
    "min_avg_volume": 500000,
    "rsi_overbought": 82,
    "rsi_oversold": 25,
    "max_daily_loss_pct": 3.0,
    "backtest_result": {}
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_trade_log() -> dict:
    if os.path.exists(TRADE_LOG):
        try:
            with open(TRADE_LOG) as f:
                return json.load(f)
        except:
            pass
    return {"trades": []}


def save_trade_log(log: dict):
    os.makedirs("signals", exist_ok=True)
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_ticker_rankings(cache: dict) -> list:
    """获取所有股票按流动性+ATR排序（只取SP500+优质股）"""
    rankings = []
    # 优先从 ticker 列表获取
    tickers = []
    sp500_file = "data_cache/sp500_tickers.json"
    if os.path.exists(sp500_file):
        try:
            with open(sp500_file) as f:
                tickers = json.load(f)
        except:
            pass
    
    # 如果没有 SP500 列表，从缓存中按平均成交量排序取前300
    if not tickers:
        all_tickers = sorted(cache.keys())
        for t in all_tickers:
            df = cache.get(t)
            if df is None or len(df) < 60:
                continue
            vol = np.mean(df["Volume"].values[-60:]) if "Volume" in df.columns else 0
            rankings.append((t, vol))
        rankings.sort(key=lambda x: -x[1])
        return [r[0] for r in rankings[:200]]
    
    # SP500 中选日均成交量 > 50万的
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        vol = np.mean(df["Volume"].values[-60:]) if "Volume" in df.columns else 0
        if vol >= 500000:
            rankings.append((t, vol))
    
    rankings.sort(key=lambda x: -x[1])
    return [r[0] for r in rankings[:200]]


def scan_intraday_signals() -> list[dict]:
    """
    扫描日内交易信号
    用日K线数据 + 成交量筛选 + 动量评分
    """
    from data_prod import load_price_cache
    cache = load_price_cache()
    if not cache:
        logger.warning("无数据缓存")
        return []

    cfg = load_config()
    tickers = get_ticker_rankings(cache)
    if not tickers:
        tickers = sorted(cache.keys())[:200]

    signals = []

    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        
        close = df["Close"].values
        price = float(close[-1])
        if price < cfg["min_price"] or price > cfg["max_price"]:
            continue

        # 成交量检查
        volume = df["Volume"].values[-1] if "Volume" in df.columns else 0
        avg_vol = np.mean(df["Volume"].values[-20:]) if "Volume" in df.columns else 1
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0

        if vol_ratio < cfg["min_volume_ratio"]:
            continue
        if avg_vol < cfg.get("min_avg_volume", 500000):
            continue

        # 多维度动量评分
        today_chg = (close[-1] - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0
        week_chg = (close[-1] - close[-6]) / close[-6] * 100 if len(close) >= 6 else 0
        month_chg = (close[-1] - close[-21]) / close[-21] * 100 if len(close) >= 21 else 0

        # RSI 过滤
        rsi = 50
        if "RSI" in df.columns:
            rsi = float(df["RSI"].values[-1])
            if rsi > cfg["rsi_overbought"]:
                continue

        # ATR
        atr = float(df["ATR_Pct"].values[-1]) if "ATR_Pct" in df.columns else 2.0

        # 均线趋势
        sma20 = df["SMA20"].values[-1] if "SMA20" in df.columns else price
        sma50 = df["SMA50"].values[-1] if "SMA50" in df.columns else sma20
        price_above_ma20 = price > sma20
        price_above_ma50 = price > sma50

        # --- 综合评分 ---
        # 1. 短中长动量加权（越短权重越高）
        mom_score = today_chg * 0.6 + week_chg * 0.25 + month_chg * 0.15
        
        # 2. 成交量确认
        vol_bonus = 0
        if vol_ratio > 3.0:
            vol_bonus = 3.0
        elif vol_ratio > 2.0:
            vol_bonus = 1.5
        elif vol_ratio > 1.5:
            vol_bonus = 0.5
        
        # 3. 趋势分数
        trend_score = 0
        if price_above_ma20:
            trend_score += 1.5
            if price_above_ma50:
                trend_score += 1.0
        else:
            trend_score -= 1.0
            if not price_above_ma50:
                trend_score -= 0.5

        # 4. ATR波动调整
        atr_adj = 0
        if atr < 1.5:
            atr_adj = 1.0
        elif atr < 2.5:
            atr_adj = 0.5
        elif atr > 4.0:
            atr_adj = -1.0

        # 5. RSI 加分（RSI 30-50 之间的上行空间大）
        rsi_score = 0
        if rsi < 35:
            rsi_score = 1.0
        elif rsi < 50:
            rsi_score = 0.5
        elif rsi > 70:
            rsi_score = -0.5

        score = mom_score + vol_bonus + trend_score + atr_adj + rsi_score

        # 风控过滤
        if today_chg > 8.0:  # 不追涨超8%
            continue
        if today_chg < -6.0:  # 不抄跌超6%
            continue

        signals.append({
            "ticker": t,
            "score": round(score, 2),
            "price": round(price, 2),
            "today_chg": round(today_chg, 2),
            "week_chg": round(week_chg, 2),
            "vol_ratio": round(vol_ratio, 2),
            "atr": round(atr, 2),
            "rsi": round(rsi, 1),
            "avg_vol": int(avg_vol),
        })

    signals.sort(key=lambda x: x["score"], reverse=True)
    max_pos = cfg.get("max_positions", 5)
    result = signals[:max_pos * 2]
    logger.info(f"日内扫描: 扫描{len(tickers)}只, 候选{len(result)}只 (取Top{max_pos})")
    return result


def generate_signal() -> dict:
    """生成今日日内交易信号"""
    signals = scan_intraday_signals()
    cfg = load_config()
    max_pos = cfg.get("max_positions", 5)

    signal = {
        "strategy": "intraday",
        "time": str(datetime.now()),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "candidates": signals[:max_pos],
        "all_scanned": len(signals),
    }

    os.makedirs("signals", exist_ok=True)
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    # 同时保存回测结果（如果有）
    bt_file = BACKTEST_FILE
    if not os.path.exists(bt_file):
        bt_result = run_backtest(days=252)
        with open(bt_file, "w") as f:
            json.dump(bt_result, f, indent=2)

    logger.info(f"信号已保存: {len(signal['candidates'])}只候选")
    return signal


def run_backtest(days: int = 252) -> dict:
    """
    日内交易回测 — 模拟每日盘中信号生成 + 持仓止盈止损
    用日K线数据近似
    """
    from data_prod import load_price_cache, compute_indicators
    cache = load_price_cache()
    if not cache:
        return {"error": "无数据"}

    cfg = load_config()
    capital = 100000
    commission = 0.001
    
    # 获取候选股票池
    tickers = get_ticker_rankings(cache)
    if not tickers:
        tickers = sorted(cache.keys())[:100]
    tickers = tickers[:100]

    all_daily_returns = []
    total_trades = 0
    wins = 0
    daily_pnls = []
    equity = capital
    peak = capital
    max_dd = 0

    # 按日期遍历
    date_set = set()
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < days:
            continue
        for dt in df.index[-days:]:
            date_set.add(str(dt)[:10])
    
    dates = sorted(date_set)
    logger.info(f"日内回测: {len(dates)}个交易日, {len(tickers)}只股票池")

    for current_date in dates:
        dt = pd.Timestamp(current_date)
        daily_pnl = 0
        day_trades = 0

        for t in tickers[:60]:  # 每天只扫描前60只
            df = cache.get(t)
            if df is None or len(df) < 60:
                continue
            
            # 找到当前日期对应的行
            try:
                idx = df.index.get_indexer([dt], method="nearest")[0]
                if idx < 1 or idx >= len(df):
                    continue
            except:
                continue

            close = df["Close"].values
            volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))
            
            price = float(close[idx])
            prev = float(close[idx-1])
            if prev <= 0:
                continue

            today_ret = (price - prev) / prev * 100
            avg_vol = np.mean(df["Volume"].values[-20:]) if "Volume" in df.columns else 1
            vol_ratio = volume[idx] / avg_vol if avg_vol > 0 else 0

            # 入场条件
            if not (today_ret > 0.5 and today_ret < 6.0 and vol_ratio > 1.3 and
                    price > 10 and price < 400):
                continue
            
            rsi_val = df["RSI"].values[idx] if "RSI" in df.columns else 50
            if rsi_val > 82:
                continue

            atr_val = df["ATR_Pct"].values[idx] if "ATR_Pct" in df.columns else 2.0
            
            qty = int(capital * cfg["per_position_pct"] / price)
            if qty <= 0:
                continue
            cost = qty * price * (1 + commission)
            if cost > capital * 0.5:  # 最多用50%资金
                continue

            capital -= cost

            # 日内模拟：持有到收盘（或止盈止损）
            sell_price = price
            exit_reason = "close"
            stop_loss_price = price * (1 - cfg["stop_loss_pct"] / 100)
            take_profit_price = price * (1 + cfg["take_profit_pct"] / 100)
            trailing_stop_price = price

            for j in range(idx + 1, min(idx + 5, len(close))):
                c = close[j]
                if np.isnan(c):
                    continue
                
                # 止损
                if c <= stop_loss_price:
                    sell_price = stop_loss_price
                    exit_reason = "stop_loss"
                    break
                
                # 追踪止损
                if c > trailing_stop_price:
                    trailing_stop_price = c
                trailing_stop = trailing_stop_price * (1 - cfg.get("trailing_stop_pct", 1.0) / 100)
                if c < trailing_stop:
                    sell_price = c
                    exit_reason = "trailing_stop"
                    break
                
                # 止盈
                if c >= take_profit_price:
                    sell_price = take_profit_price
                    exit_reason = "take_profit"
                    break
                
                sell_price = c

            proceeds = qty * sell_price * (1 - commission)
            pnl = proceeds - cost
            capital += proceeds
            daily_pnl += pnl
            day_trades += 1
            total_trades += 1
            if pnl > 0:
                wins += 1

        if day_trades > 0:
            daily_pnls.append(daily_pnl)
            equity += daily_pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)

    total_return = (capital - 100000) / 100000 * 100
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_return = np.mean(daily_pnls) if daily_pnls else 0

    result = {
        "strategy": "intraday",
        "total_return_pct": round(total_return, 2),
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 1),
        "avg_return_per_trade_pct": round(avg_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "test_period_days": days,
        "test_dates": len(dates),
    }

    # 保存回测结果到config
    cfg["backtest_result"] = result
    save_config(cfg)

    logger.info(f"日内回测: 收益{total_return:+.2f}% 胜率{win_rate:.0f}% 交易{total_trades}次 回撤{max_dd:.1f}%")
    return result


def show_status():
    """查看日内交易状态"""
    signal = {}
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            signal = json.load(f)

    trade_log = load_trade_log()
    cfg = load_config()

    print("\n" + "=" * 55)
    print("  ⚡ 日内交易模块")
    print("=" * 55)
    print(f"  启用: {'🟢' if cfg.get('enabled') else '🔴'} {cfg.get('max_positions',5)}只 止损{cfg.get('stop_loss_pct',1.5)}% 止盈{cfg.get('take_profit_pct',2.5)}%")
    
    if signal and signal.get("candidates"):
        print(f"  信号时间: {signal.get('time','-')[:16]}")
        print(f"  候选: {len(signal.get('candidates',[]))} 只")
        for s in signal["candidates"]:
            print(f"    {s['ticker']:6s} 评分{s['score']:+.1f}  ${s['price']:.2f} 今日{s['today_chg']:+.2f}%")
    else:
        print("  📭 无信号")

    bt = cfg.get("backtest_result", {})
    if bt and bt.get("total_trades", 0) > 0:
        print(f"\n  回测 ({bt.get('test_period_days','?')}天):")
        print(f"    收益: {bt.get('total_return_pct',0):+.2f}%  胜率: {bt.get('win_rate_pct',0):.0f}%")
        print(f"    交易: {bt.get('total_trades',0)}次  回撤: {bt.get('max_drawdown_pct',0):.1f}%")

    trades = trade_log.get("trades", [])
    if trades:
        print(f"\n  历史交易: {len(trades)} 笔")

    print("=" * 55)


if __name__ == "__main__":
    if "--scan" in sys.argv:
        s = generate_signal()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif "--backtest" in sys.argv:
        run_backtest(days=252)
    elif "--status" in sys.argv:
        show_status()
    else:
        print(__doc__)
