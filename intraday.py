"""
日内交易策略 — 完全独立于主策略
================================
- 盘中实时动量选股
- 当日开仓当日平仓（收盘前强制清仓）
- 独立信号/日志/回测
- 独立资金分配

用法：
  python3 intraday.py --scan       扫描今日信号
  python3 intraday.py --backtest   回测
  python3 intraday.py --status     查看状态
"""

import os, sys, json, logging, numpy as np, pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger("quant.intraday")

SIGNAL_FILE = "signals/intraday_signal.json"
TRADE_LOG = "signals/intraday_trades.json"
CONFIG_FILE = "config/intraday_config.json"
CACHE_DIR = "data_cache"

DEFAULT_CONFIG = {
    "enabled": False,
    "max_positions": 3,
    "per_position_pct": 0.15,
    "capital_pct": 0.20,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 3.0,
    "scan_interval_minutes": 30,
    "close_time": "15:50",
    "momentum_windows": [15, 30, 60],
    "min_price": 10,
    "max_price": 500,
    "min_volume_ratio": 1.2,
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
        with open(TRADE_LOG) as f:
            return json.load(f)
    return {"trades": []}


def save_trade_log(log: dict):
    os.makedirs("signals", exist_ok=True)
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def load_1min_kline(symbol: str, days: int = 5) -> list[dict]:
    """获取1分钟K线（东财/sina备用）"""
    try:
        import requests, re, json as _json
        # 先用东财
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.{symbol}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57&klt=1&fqt=1&lmt={days*240}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json().get("data", {})
        klines = data.get("klines", [])
        if klines:
            result = []
            for k in klines:
                parts = k.split(",")
                if len(parts) >= 6:
                    result.append({"time": parts[0], "open": float(parts[1]), "close": float(parts[4]),
                                    "high": float(parts[2]), "low": float(parts[3]), "volume": float(parts[5])})
            return result
    except:
        pass
    return []


def scan_intraday_signals() -> list[dict]:
    """
    扫描日内交易信号
    用日K线数据近似计算日内动量排名
    """
    from data_prod import load_price_cache
    cache = load_price_cache()
    if not cache:
        return []

    cfg = load_config()
    tickers = sorted(cache.keys())[:100]
    signals = []

    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        close = df["Close"].values
        price = float(close[-1])
        if price < cfg["min_price"] or price > cfg["max_price"]:
            continue

        # 多维度日内动量评分
        today_chg = (close[-1] - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0
        week_chg = (close[-1] - close[-6]) / close[-6] * 100 if len(close) >= 6 else 0
        month_chg = (close[-1] - close[-21]) / close[-21] * 100 if len(close) >= 21 else 0

        volume = df["Volume"].values[-1] if "Volume" in df.columns else 0
        vol_ma = np.mean(df["Volume"].values[-20:]) if len(df["Volume"].values) >= 20 else 1
        vol_ratio = volume / vol_ma if vol_ma > 0 else 0

        if vol_ratio < cfg["min_volume_ratio"]:
            continue

        # RSI 过滤（RSI > 80 不追高）
        rsi = None
        if "RSI" in df.columns:
            rsi = float(df["RSI"].values[-1])
            if rsi > 85:
                continue

        # 波动率调整（高波限制买入量）
        atr = df["ATR_Pct"].values[-1] if "ATR_Pct" in df.columns else 2.0

        # 综合评分：短中长动量加权 + 成交量确认
        mom_score = today_chg * 0.5 + week_chg * 0.3 + month_chg * 0.2
        vol_bonus = 0
        if vol_ratio > 2.0:
            vol_bonus = 2.0
        elif vol_ratio > 1.5:
            vol_bonus = 1.0

        # 均线趋势加分（价格在SMA20之上加分）
        sma20 = df["SMA20"].values[-1] if "SMA20" in df.columns else price
        trend_bonus = 1.0 if price > sma20 else -1.0

        # ATR调整（高波动扣分，低波动加分）
        vol_penalty = -0.5 if atr > 3.0 else (0.5 if atr < 1.5 else 0)

        score = mom_score + vol_bonus + trend_bonus + vol_penalty

        # 风控：今日涨幅过高不追（>8%）
        if today_chg > 8.0:
            continue
        signals.append({
            "ticker": t,
            "score": round(score, 2),
            "price": round(price, 2),
            "today_chg": round(today_chg, 2),
            "week_chg": round(week_chg, 2),
            "vol_ratio": round(vol_ratio, 2),
        })

    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals[:cfg["max_positions"] * 2]


def generate_signal() -> dict:
    """生成今日日内交易信号"""
    signals = scan_intraday_signals()
    cfg = load_config()

    signal = {
        "strategy": "intraday",
        "time": str(datetime.now()),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "candidates": signals[:cfg["max_positions"]],
        "all_scanned": len(signals),
    }

    os.makedirs("signals", exist_ok=True)
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    return signal


def run_backtest(days: int = 365) -> dict:
    """
    日内交易回测
    用日K线模拟：每日开盘买入信号股，收盘卖出
    """
    from data_prod import load_price_cache, compute_indicators
    cache = load_price_cache()
    if not cache:
        return {"error": "无数据"}

    cfg = load_config()
    tickers = sorted(cache.keys())[:100]
    capital = 100000
    commission = 0.001

    trade_log = []
    daily_returns = []
    total_trades = 0
    wins = 0

    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < days:
            continue
        close = df["Close"].values
        volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))
        vol_ma = pd.Series(volume).rolling(20).mean().values

        for i in range(1, len(close)):
            if np.isnan(close[i]) or close[i] <= 0:
                continue
            price = close[i]
            prev = close[i-1]
            if prev <= 0:
                continue

            today_ret = (price - prev) / prev * 100
            vol_ratio = volume[i] / vol_ma[i] if vol_ma[i] > 0 else 0

            # 改进的入场条件
            atr_val = df["ATR_Pct"].values[i] if "ATR_Pct" in df.columns else 2.0
            rsi_val = df["RSI"].values[i] if "RSI" in df.columns else 50

            if today_ret > 0.5 and today_ret < 5.0 and vol_ratio > 1.3 and \
               price > 10 and price < 500 and rsi_val < 80:
                qty = int(capital * cfg["per_position_pct"] / price)
                if qty <= 0:
                    continue
                cost = qty * price * (1 + commission)
                if cost > capital:
                    continue
                capital -= cost

                # 日内持有 + 止盈止损
                sell_price = price
                exit_chg = 0
                for j in range(i, min(i + 3, len(close))):
                    c = close[j]
                    ret = (c - price) / price * 100
                    if ret < -2.0:  # 止损 -2%
                        sell_price = price * 0.98
                        break
                    if ret > 3.0:  # 止盈 +3%
                        sell_price = price * 1.03
                        break
                    sell_price = c

                proceeds = qty * sell_price * (1 - commission)
                pnl = proceeds - cost
                capital += proceeds
                total_trades += 1
                if pnl > 0:
                    wins += 1
                daily_returns.append(pnl / cost * 100 if cost > 0 else 0)

    total_return = (capital - 100000) / 100000 * 100
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_return = np.mean(daily_returns) if daily_returns else 0
    max_dd = 0
    peak = 100000
    eq = 100000
    for r in daily_returns:
        eq += eq * r / 100
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)

    result = {
        "strategy": "intraday",
        "total_return_pct": round(total_return, 2),
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 1),
        "avg_return_per_trade_pct": round(avg_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "test_period_days": days,
    }

    logger.info(f"日内回测: 收益{total_return:+.2f}% 胜率{win_rate:.0f}% 交易{total_trades}次 回撤{max_dd:.1f}%")
    return result


def show_status():
    """查看日内交易状态"""
    signal = {}
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            signal = json.load(f)

    trade_log = load_trade_log()

    print("\n" + "=" * 55)
    print("  ⚡ 日内交易模块")
    print("=" * 55)

    if signal and signal.get("candidates"):
        print(f"  信号时间: {signal.get('time','-')[:16]}")
        print(f"  候选: {len(signal.get('candidates',[]))} 只")
        for s in signal["candidates"]:
            print(f"    {s['ticker']:6s} 评分{s['score']:+.1f}  ${s['price']:.2f} 今日{s['today_chg']:+.2f}%")
    else:
        print("  📭 无信号")

    trades = trade_log.get("trades", [])
    if trades:
        today_trades = [t for t in trades if t.get("date", "")[:10] == datetime.now().strftime("%Y-%m-%d")]
        print(f"\n  今日交易: {len(today_trades)} 笔")
        print(f"  历史交易: {len(trades)} 笔")

    print("=" * 55)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    if "--scan" in sys.argv:
        s = generate_signal()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif "--backtest" in sys.argv:
        run_backtest()
    elif "--status" in sys.argv:
        show_status()
    else:
        print(__doc__)
