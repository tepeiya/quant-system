"""期货跨品种套利 — 完整策略 + 精确回测"""
import logging, json, numpy as np, os
from datetime import datetime
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quant.futures")

# ===== 期货品种参数 =====
FUTURES = {
    "RB": {"name": "螺纹钢", "exchange": "SHFE", "unit": 10, "margin": 0.10, "symbol_sina": "RB0"},
    "HC": {"name": "热卷",   "exchange": "SHFE", "unit": 10, "margin": 0.10, "symbol_sina": "HC0"},
    "SC": {"name": "原油",   "exchange": "INE",  "unit": 1000, "margin": 0.10, "symbol_sina": "SC0"},
    "MA": {"name": "甲醇",   "exchange": "ZXE",  "unit": 10, "margin": 0.10, "symbol_sina": "MA0"},
    "Y":  {"name": "豆油",   "exchange": "DCE",  "unit": 10, "margin": 0.10, "symbol_sina": "Y0"},
    "P":  {"name": "棕榈油", "exchange": "DCE",  "unit": 10, "margin": 0.10, "symbol_sina": "P0"},
    "I":  {"name": "铁矿石", "exchange": "DCE",  "unit": 100, "margin": 0.12, "symbol_sina": "I0"},
    "ZN": {"name": "锌",     "exchange": "SHFE", "unit": 5, "margin": 0.08, "symbol_sina": "ZN0"},
    "CU": {"name": "铜",     "exchange": "SHFE", "unit": 5, "margin": 0.08, "symbol_sina": "CU0"},
    "AU": {"name": "黄金",   "exchange": "SHFE", "unit": 1000, "margin": 0.08, "symbol_sina": "AU0"},
    "AG": {"name": "白银",   "exchange": "SHFE", "unit": 15, "margin": 0.08, "symbol_sina": "AG0"},
}

# ===== 推荐的品种对 =====
RECOMMENDED_PAIRS = {
    "RB-HC":  {"a": "RB", "b": "HC", "name": "螺纹钢-热卷", "enabled": True, "max_hold": 15},
    "SC-MA":  {"a": "SC", "b": "MA", "name": "原油-甲醇",   "enabled": True, "max_hold": 20},
    "Y-P":    {"a": "Y",  "b": "P",  "name": "豆油-棕榈油", "enabled": False, "max_hold": 20},
    "I-RB":   {"a": "I",  "b": "RB", "name": "铁矿石-螺纹钢","enabled": False, "max_hold": 20},
    "CU-ZN":  {"a": "CU", "b": "ZN", "name": "铜-锌",       "enabled": False, "max_hold": 20},
    "AU-AG":  {"a": "AU", "b": "AG", "name": "黄金-白银",   "enabled": False, "max_hold": 20},
}


def fetch_kline(sina_symbol: str, days: int = 500) -> list[dict]:
    """获取期货日K线"""
    import requests, re, json
    url = f"https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20x=/InnerFuturesNewService.getDailyKLine?symbol={sina_symbol}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0",
                                        "Referer": "https://finance.sina.com.cn"}, timeout=15)
        m = re.search(r'\[.+\]', r.text)
        if not m:
            return []
        items = json.loads(m.group(0))
        items = items[-days:] if len(items) > days else items
        return [{"date": it["d"], "open": float(it["o"]), "high": float(it["h"]),
                 "low": float(it["l"]), "close": float(it["c"]), "volume": int(it["v"])}
                for it in items]
    except:
        return []


def calc_eg_cointegration(price_a: np.ndarray, price_b: np.ndarray):
    """
    Engle-Granger 两步协整检验
    返回：{hedge_ratio, half_life, residual_adf_stat, zscore}
    """
    log_a = np.log(price_a)
    log_b = np.log(price_b)
    n = len(log_a)

    # 第一步：OLS 回归
    X = np.vstack([log_b, np.ones(n)]).T
    coeffs = np.linalg.lstsq(X, log_a, rcond=None)[0]
    hedge = coeffs[0]
    intercept = coeffs[1]

    # 残差 = 价差
    residual = log_a - hedge * log_b - intercept
    mean = np.mean(residual)
    std = np.std(residual)
    zscore = (residual[-1] - mean) / std if std > 0 else 0

    # 半衰期（均值回归速度）
    diff = np.diff(residual)
    lag = residual[:-1]
    lag_mean = lag - np.mean(lag)
    X2 = np.vstack([lag_mean, np.ones(len(lag_mean))]).T
    try:
        coeffs2 = np.linalg.lstsq(X2, diff, rcond=None)[0]
        half_life = -np.log(2) / coeffs2[0] if coeffs2[0] < 0 else 999
    except:
        half_life = 999

    return {
        "hedge_ratio": float(hedge),
        "intercept": float(intercept),
        "residual_mean": float(mean),
        "residual_std": float(std),
        "zscore": float(zscore),
        "half_life": float(half_life),
        "residuals": residual.tolist(),
    }


def backtest_pair(pid: str, pair_info: dict,
                  window: int = 60,
                  z_entry: float = 1.5,
                  z_exit: float = 0.3,
                  z_stop: float = 3.0,
                  capital: float = 100000) -> dict:
    """完整回测单个品种对"""
    sym_a = pair_info["a"]
    sym_b = pair_info["b"]
    info_a = FUTURES[sym_a]
    info_b = FUTURES[sym_b]

    klines_a = fetch_kline(info_a["symbol_sina"], days=1000)
    klines_b = fetch_kline(info_b["symbol_sina"], days=1000)

    if len(klines_a) < 120 or len(klines_b) < 120:
        return {"error": f"数据不足: {len(klines_a)}/{len(klines_b)}"}

    closes_a = np.array([k["close"] for k in klines_a])
    closes_b = np.array([k["close"] for k in klines_b])
    dates = [k["date"] for k in klines_a]
    n = min(len(closes_a), len(closes_b))

    # 按期货手数计算
    unit_a = info_a["unit"]
    unit_b = info_b["unit"]
    margin_a = info_a["margin"]
    margin_b = info_b["margin"]

    log_a = np.log(closes_a[:n])
    log_b = np.log(closes_b[:n])

    cash = capital
    trades = 0
    wins = 0
    in_pos = False
    hold_days = 0
    entry_z = 0
    entry_hedge = 0
    entry_price_a = 0
    entry_price_b = 0
    peak = capital
    max_dd = 0
    equity_curve = []

    for i in range(window + 1, n):
        ya = log_a[i-window:i]
        yb = log_b[i-window:i]

        # EG 协整
        X = np.vstack([yb, np.ones(window)]).T
        coeffs = np.linalg.lstsq(X, ya, rcond=None)[0]
        hedge = coeffs[0]
        intercept = coeffs[1]

        residual = ya - hedge * yb - intercept
        mean = np.mean(residual)
        std = np.std(residual)
        cur_residual = log_a[i] - hedge * log_b[i] - intercept
        z = (cur_residual - mean) / std if std > 0 else 0

        if not in_pos:
            if abs(z) > z_entry:
                in_pos = True
                entry_z = z
                entry_hedge = hedge
                hold_days = 0
                entry_price_a = closes_a[i]
                entry_price_b = closes_b[i]
                trades += 1
        else:
            hold_days += 1
            should_close = (abs(z) < z_exit or abs(z) > z_stop or hold_days > pair_info.get("max_hold", 20))

            if should_close:
                price_a = closes_a[i]
                price_b = closes_b[i]

                # 价差回归收益：用对冲比计算每手对冲组合的盈亏
                lot_a = 1  # 每配对各 1 手
                lot_b = int(round(abs(entry_hedge) * unit_a / unit_b))  # 根据对冲比算B手数
                lot_b = max(1, lot_b)

                # 对冲组合价值变化
                if z > 0:
                    # 做空 A + 做多 B（价差偏高，期望回落）
                    pnl = (entry_price_a - price_a) * unit_a * lot_a + \
                          (price_b - entry_price_b) * unit_b * lot_b
                else:
                    # 做多 A + 做空 B（价差偏低，期望回升）
                    pnl = (price_a - entry_price_a) * unit_a * lot_a + \
                          (entry_price_b - price_b) * unit_b * lot_b

                cash += pnl
                if pnl > 0:
                    wins += 1
                in_pos = False

        equity = cash
        equity_curve.append(equity)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    total_return = (cash - capital) / capital * 100
    years = n / 250
    annual = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
    win_rate = wins / trades * 100 if trades > 0 else 0
    corr = float(np.corrcoef(log_a, log_b)[0, 1])

    return {
        "pair": pid,
        "name": pair_info["name"],
        "total_return_pct": round(total_return, 2),
        "annual_return_pct": round(annual, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trades": trades,
        "wins": wins,
        "win_rate_pct": round(win_rate, 1),
        "correlation": round(corr, 3),
        "period_years": round(years, 1),
        "latest_zscore": round(z, 2),
    }


def run_backtest_all():
    """回测所有启用的配对"""
    results = []
    for pid, info in RECOMMENDED_PAIRS.items():
        if not info["enabled"]:
            continue
        print(f"  回测 {pid} {info['name']}...")
        r = backtest_pair(pid, info)
        if "error" in r:
            print(f"    ❌ {r['error']}")
            continue
        results.append(r)
        print(f"    ✅ 收益{r['total_return_pct']:>+7.2f}% 年化{r['annual_return_pct']:>+6.2f}% "
              f"回撤{r['max_drawdown_pct']:>5.2f}% 胜率{r['win_rate_pct']:>5.1f}%")
    return results


def scan_signals() -> list[dict]:
    """扫描当前配对信号"""
    signals = []
    for pid, info in RECOMMENDED_PAIRS.items():
        if not info["enabled"]:
            continue
        sym_a, sym_b = info["a"], info["b"]
        klines_a = fetch_kline(FUTURES[sym_a]["symbol_sina"], days=120)
        klines_b = fetch_kline(FUTURES[sym_b]["symbol_sina"], days=120)
        if len(klines_a) < 60 or len(klines_b) < 60:
            continue

        closes_a = np.array([k["close"] for k in klines_a])
        closes_b = np.array([k["close"] for k in klines_b])
        n = min(len(closes_a), len(closes_b))

        eg = calc_eg_cointegration(closes_a[:n], closes_b[:n])

        z = eg["zscore"]
        half_life = eg["half_life"]

        if abs(z) > 1.5 and half_life < 30:
            status = "开仓信号"
            direction = "做空A做多B" if z > 0 else "做多A做空B"
        elif abs(z) < 0.5:
            status = "中性"
            direction = "-"
        else:
            status = "观察"
            direction = "-" if abs(z) < 1.0 else ("做空A做多B" if z > 0 else "做多A做空B")

        price_a = closes_a[-1]
        price_b = closes_b[-1]

        signals.append({
            "pair": pid,
            "name": info["name"],
            "zscore": round(z, 2),
            "half_life_days": round(half_life, 1),
            "hedge_ratio": round(eg["hedge_ratio"], 4),
            "status": status,
            "direction": direction,
            "price_a": round(price_a, 0),
            "price_b": round(price_b, 0),
        })

    # 保存信号
    signal_file = "signals/futures_signal.json"
    os.makedirs("signals", exist_ok=True)
    with open(signal_file, "w") as f:
        json.dump({"strategy": "futures_pairs", "time": str(datetime.now()),
                    "signals": signals}, f, indent=2)

    return signals


if __name__ == "__main__":
    import sys
    if "--backtest" in sys.argv:
        print("\n期货跨品种套利回测")
        print("=" * 55)
        results = run_backtest_all()
        print("=" * 55)
        if results:
            best = max(results, key=lambda x: x["total_return_pct"])
            print(f"最佳: {best['pair']} 收益{best['total_return_pct']:+.2f}%")
    elif "--scan" in sys.argv:
        signals = scan_signals()
        print(f"\n当前信号 ({len(signals)}个配对):")
        print("=" * 55)
        for s in signals:
            icon = "🟢" if s["status"] == "开仓信号" else "⚪" if s["status"] == "中性" else "🟡"
            print(f"  {icon} {s['pair']:8s} {s['name']:12s} z={s['zscore']:+.2f}  半衰期{s['half_life_days']:>5.1f}天  {s['status']}")
        print("=" * 55)
    else:
        print(__doc__)
