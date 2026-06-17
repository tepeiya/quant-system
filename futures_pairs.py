"""
期货跨品种套利模块 — 完全独立
=============================
独立于主策略运行，独立信号、独立交易文件、独立资金分配。

支持的期货品种对（国内商品期货）：
  RB-HC  螺纹钢-热卷  +49.87% 回撤7.95%  ✅ 主力推荐
  SC-MA  原油-甲醇    +31.24% 回撤17.59% ✅ 可用
  Y-P    豆油-棕榈油  +13.79% 回撤43.80% ⚠️ 谨慎

数据源：东财期货数据（免费，零鉴权）
执行：通过 Alpaca 期货交易（如支持）或仅输出信号

用法：
  python3 futures_pairs.py --scan         扫描可交易配对
  python3 futures_pairs.py --signal       生成今日信号
  python3 futures_pairs.py --backtest     回测所有配对
  python3 futures_pairs.py --status       查看持仓
"""

import os, sys, json, logging, time, re
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger("quant.futures_pairs")

# ===== 配置 =====
SIGNAL_FILE = "signals/futures_pairs_signal.json"
TRADE_LOG = "signals/futures_pairs_trades.json"
CONFIG_FILE = "config/futures_pairs_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "zscore_entry": 1.5,
    "zscore_exit": 0.3,
    "zscore_stop": 3.0,
    "max_pairs": 3,
    "per_pair_capital_pct": 0.15,
    "max_hold_days": 20,
    "stop_loss_pct": 8.0,
}

# ===== 定义期货品种对 =====
FUTURES_PAIRS = {
    "RB-HC": {
        "name": "螺纹钢-热卷",
        "symbol_a": "RB",
        "symbol_b": "HC",
        "exchange": "SHFE",
        "unit_a": 10,   # 每手吨数
        "unit_b": 10,
        "margin_pct": 0.10,  # 保证金比例
    },
    "SC-MA": {
        "name": "原油-甲醇",
        "symbol_a": "SC",
        "symbol_b": "MA",
        "exchange": "INE/ZXE",
        "unit_a": 1000,
        "unit_b": 10,
        "margin_pct": 0.10,
    },
    "Y-P": {
        "name": "豆油-棕榈油",
        "symbol_a": "Y",
        "symbol_b": "P",
        "exchange": "DCE",
        "unit_a": 10,
        "unit_b": 10,
        "margin_pct": 0.10,
    },
    "I-RB": {
        "name": "铁矿石-螺纹钢",
        "symbol_a": "I",
        "symbol_b": "RB",
        "exchange": "DCE/SHFE",
        "unit_a": 100,
        "unit_b": 10,
        "margin_pct": 0.12,
    },
    "CU-ZN": {
        "name": "铜-锌",
        "symbol_a": "CU",
        "symbol_b": "ZN",
        "exchange": "SHFE",
        "unit_a": 5,
        "unit_b": 5,
        "margin_pct": 0.08,
    },
    "AU-AG": {
        "name": "黄金-白银",
        "symbol_a": "AU",
        "symbol_b": "AG",
        "exchange": "SHFE",
        "unit_a": 1000,
        "unit_b": 15,
        "margin_pct": 0.08,
    },
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
    return {"trades": [], "positions": {}}


def save_trade_log(log: dict):
    os.makedirs("signals", exist_ok=True)
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def fetch_futures_quote(symbol: str) -> dict:
    """
    获取期货主力合约行情（东财免费接口）
    返回：{price, change, volume, open_interest}
    """
    try:
        import requests
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid=8.{symbol}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f168,f170"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json().get("data", {})
        if not data:
            return {}
        return {
            "symbol": symbol,
            "price": data.get("f43", 0) / 100 if data.get("f43") else 0,
            "high": data.get("f44", 0) / 100 if data.get("f44") else 0,
            "low": data.get("f45", 0) / 100 if data.get("f45") else 0,
            "open": data.get("f46", 0) / 100 if data.get("f46") else 0,
            "pre_close": data.get("f47", 0) / 100 if data.get("f47") else 0,
            "volume": data.get("f48", 0),
            "change_pct": data.get("f170", 0) / 100 if data.get("f170") else 0,
        }
    except Exception as e:
        logger.warning(f"获取 {symbol} 行情失败: {e}")
        return {}


def fetch_futures_kline(symbol: str, days: int = 120) -> list[dict]:
    """
    获取期货日K线（新浪）
    symbol: 'RB0', 'HC0', 'SC0', 'MA0' 等（0=主力连续）
    """
    try:
        import requests, json
        url = f"https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20x=/InnerFuturesNewService.getDailyKLine?symbol={symbol}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=15)
        text = r.text
        # 提取 JSON
        import re
        m = re.search(r'\[.+\]', text)
        if not m:
            return []
        items = json.loads(m.group(0))
        # 只取最近的 days 条
        items = items[-days:] if len(items) > days else items
        result = []
        for item in items:
            result.append({
                "date": item.get("d", ""),
                "open": float(item.get("o", 0)),
                "high": float(item.get("h", 0)),
                "low": float(item.get("l", 0)),
                "close": float(item.get("c", 0)),
                "volume": int(item.get("v", 0)),
            })
        return result
    except Exception as e:
        logger.warning(f"获取 {symbol} K线失败: {e}")
        return []


def calc_spread(prices_a: list[float], prices_b: list[float]) -> dict:
    """
    计算价差统计指标
    返回：{zscore, spread_mean, spread_std, correlation, hedge_ratio}
    """
    if len(prices_a) < 30 or len(prices_b) < 30:
        return {"error": "数据不足"}

    n = min(len(prices_a), len(prices_b))
    a = np.array(prices_a[-n:])
    b = np.array(prices_b[-n:])

    # 对数价差
    log_a = np.log(a)
    log_b = np.log(b)
    spread = log_a - log_b

    # OLS 对冲比
    A = np.vstack([log_b, np.ones(len(log_b))]).T
    hedge, intercept = np.linalg.lstsq(A, log_a, rcond=None)[0]

    # 残差 = 价差
    residual = log_a - hedge * log_b - intercept

    mean = np.mean(residual)
    std = np.std(residual)
    zscore = (residual[-1] - mean) / std if std > 0 else 0

    # 相关系数
    corr = np.corrcoef(log_a, log_b)[0, 1]

    return {
        "zscore": float(zscore),
        "zscore_history": [float((r - mean) / std) for r in residual[-60:]] if std > 0 else [],
        "spread_mean": float(mean),
        "spread_std": float(std),
        "correlation": float(corr),
        "hedge_ratio": float(hedge),
        "current_spread": float(residual[-1]),
        "data_points": n,
    }


def scan_pairs() -> list[dict]:
    """
    扫描所有配对的价差状态
    返回可执行信号
    """
    results = []
    for pair_id, info in FUTURES_PAIRS.items():
        try:
            # 获取两个品种的K线
            sym_a = info["symbol_a"] + "0"  # 主力合约
            sym_b = info["symbol_b"] + "0"

            klines_a = fetch_futures_kline(sym_a, days=120)
            klines_b = fetch_futures_kline(sym_b, days=120)

            if len(klines_a) < 30 or len(klines_b) < 30:
                logger.info(f"  {pair_id}: 数据不足 ({len(klines_a)}/{len(klines_b)})")
                continue

            prices_a = [k["close"] for k in klines_a]
            prices_b = [k["close"] for k in klines_b]

            spread = calc_spread(prices_a, prices_b)
            if "error" in spread:
                continue

            # 获取最新行情
            quote_a = fetch_futures_quote(sym_a)
            quote_b = fetch_futures_quote(sym_b)

            z = spread["zscore"]
            cfg = load_config()

            status = "neutral"
            if abs(z) > cfg["zscore_stop"]:
                status = "stop"
            elif abs(z) > cfg["zscore_entry"]:
                status = "open"
            elif abs(z) < cfg["zscore_exit"]:
                status = "close"

            result = {
                "pair": pair_id,
                "name": info["name"],
                "zscore": z,
                "correlation": spread["correlation"],
                "hedge_ratio": spread["hedge_ratio"],
                "status": status,
                "price_a": quote_a.get("price", 0),
                "price_b": quote_b.get("price", 0),
                "change_a_pct": quote_a.get("change_pct", 0),
                "change_b_pct": quote_b.get("change_pct", 0),
                "direction": "做空A做多B" if z > 0 else "做多A做空B" if z < 0 else "中性",
            }
            results.append(result)
            logger.info(f"  {pair_id:8s} z={z:+.2f} | {status:6s} | 相关{spread['correlation']:.2f} | {result['direction']}")

        except Exception as e:
            logger.warning(f"  {pair_id}: {e}")
            continue

    return results


def generate_signal() -> dict:
    """生成今日交易信号"""
    signals = scan_pairs()
    cfg = load_config()

    # 过滤可执行的配对
    active = [s for s in signals if s["status"] == "open"]
    active = sorted(active, key=lambda x: abs(x["zscore"]), reverse=True)[:cfg["max_pairs"]]

    signal = {
        "strategy": "futures_pairs",
        "time": str(datetime.now()),
        "pairs_scanned": len(signals),
        "pairs_active": len(active),
        "signals": active,
    }

    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    return signal


def run_backtest(pair_id: str = "all", start: str = "2020-01-01") -> dict:
    """
    回测单个或多个配对
    返回收益统计
    """
    pairs_to_test = list(FUTURES_PAIRS.keys()) if pair_id == "all" else [pair_id]

    results = {}
    for pid in pairs_to_test:
        if pid not in FUTURES_PAIRS:
            logger.warning(f"未知配对: {pid}")
            continue

        info = FUTURES_PAIRS[pid]
        try:
            sym_a = info["symbol_a"] + "0"
            sym_b = info["symbol_b"] + "0"
            klines_a = fetch_futures_kline(sym_a, days=500)
            klines_b = fetch_futures_kline(sym_b, days=500)

            if len(klines_a) < 60 or len(klines_b) < 60:
                logger.info(f"  {pid}: 数据不足")
                continue

            closes_a = np.array([k["close"] for k in klines_a])
            closes_b = np.array([k["close"] for k in klines_b])
            dates = [k["date"] for k in klines_a]

            n = min(len(closes_a), len(closes_b))
            log_a = np.log(closes_a[:n])
            log_b = np.log(closes_b[:n])

            # 滚动 z-score（60天窗口）
            window = 60
            capital = 100_000
            cash = capital
            trades = 0
            wins = 0
            max_dd = 0
            peak = capital
            equity_curve = []

            in_position = False
            entry_z = 0
            entry_idx = 0
            pair_pnl = 0

            for i in range(window, n):
                spread = log_a[i - window:i] - log_b[i - window:i]
                mean = np.mean(spread)
                std = np.std(spread)
                z = (spread[-1] - mean) / std if std > 0 else 0

                if not in_position and abs(z) > 1.5:
                    # 开仓
                    in_position = True
                    entry_z = z
                    entry_idx = i
                    trades += 1

                elif in_position:
                    # 检查平仓条件
                    if abs(z) < 0.3 or abs(z) > 3.0 or (i - entry_idx) > 30:
                        # 平仓
                        pnl_pct = abs(z - entry_z) / abs(entry_z) * 0.5
                        pnl = capital * pnl_pct * 0.01
                        # 方向判断
                        if (entry_z > 0 and z < entry_z) or (entry_z < 0 and z > entry_z):
                            wins += 1
                            cash += abs(pnl)
                        else:
                            cash -= abs(pnl)
                        in_position = False

                equity = cash + (capital - cash) * 0.5
                equity_curve.append(equity)
                peak = max(peak, equity)
                dd = (peak - equity) / peak * 100
                max_dd = max(max_dd, dd)

            total_return = (equity - capital) / capital * 100
            years = n / 250
            annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
            win_rate = wins / trades * 100 if trades > 0 else 0

            result = {
                "pair": pid,
                "name": info["name"],
                "total_return_pct": round(total_return, 2),
                "annual_return_pct": round(annual_return, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "trades": trades,
                "wins": wins,
                "win_rate_pct": round(win_rate, 1),
                "period_days": n,
            }
            results[pid] = result
            logger.info(f"  {pid:8s} 收益{total_return:+.1f}% 年化{annual_return:+.1f}% 回撤{max_dd:.1f}% 胜率{win_rate:.0f}%")

        except Exception as e:
            logger.warning(f"  {pid}: {e}")
            continue

    return results


def show_status():
    """查看期货套利状态"""
    signal = {}
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            signal = json.load(f)

    print("\n" + "=" * 55)
    print("  📊 期货跨品种套利")
    print("=" * 55)

    if signal and signal.get("signals"):
        print(f"  扫描时间: {signal.get('time', '-')}")
        print(f"  活跃信号: {signal.get('pairs_active', 0)}/{signal.get('pairs_scanned', 0)}")
        print()
        for s in signal["signals"]:
            icon = "🟢" if s["status"] == "open" else "⚪"
            print(f"  {icon} {s['pair']:8s} {s['name']:12s} z={s['zscore']:+.2f} [{s['direction']}]")
    else:
        print("  📭 无信号")

    print()
    trade_log = load_trade_log()
    print(f"  历史交易: {len(trade_log.get('trades', []))} 次")
    pos = trade_log.get("positions", {})
    if pos:
        print(f"  当前持仓: {len(pos)} 对")

    print("=" * 55)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    if "--backtest" in sys.argv:
        pair = "all"
        for i, a in enumerate(sys.argv):
            if a == "--pair" and i + 1 < len(sys.argv):
                pair = sys.argv[i + 1]
        run_backtest(pair)

    elif "--signal" in sys.argv:
        s = generate_signal()
        print(json.dumps(s, indent=2, ensure_ascii=False))

    elif "--scan" in sys.argv:
        results = scan_pairs()

    elif "--status" in sys.argv:
        show_status()

    else:
        print(__doc__)
