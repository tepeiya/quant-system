"""
绩效归因系统
===========
功能：
1. 从交易日志 + 账户历史计算绩效指标
2. 因子贡献分解（每个因子对收益的贡献度）
3. 交易行为分析（胜率、持仓时间、集中度）
4. Web面板展示（/trades/ 页面）

运行：
  python3 performance_attribution.py         # 终端输出
  python3 performance_attribution.py --json  # JSON格式供Web调用
"""

import os
import json
import logging
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger("quant.perf")

TRADE_LOG_FILE = "signals/trade_log.json"
PORTFOLIO_FILE = "signals/portfolio.json"
PERF_CACHE = "data_cache/performance_cache.json"
os.makedirs("data_cache", exist_ok=True)


# ===== 1. 交易统计 =====

def load_trades() -> list:
    """加载交易日志"""
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE) as f:
            return json.load(f)
    return []


def load_portfolio_history() -> list:
    """从缓存加载历史持仓记录（如果有）"""
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            p = json.load(f)
            if p and p.get("last_update"):
                return [p]
    return []


def compute_trade_stats(trades: list) -> dict:
    """交易统计"""
    if not trades:
        return {"total_trades": 0, "message": "暂无交易记录"}

    buys = [t for t in trades if t.get("side","").upper() == "BUY"]
    sells = [t for t in trades if t.get("side","").upper() == "SELL"]

    # 模拟配对：同一股票的先买后卖
    by_symbol = {}
    for t in trades:
        s = t.get("symbol","")
        by_symbol.setdefault(s, []).append(t)

    win_trades = 0
    loss_trades = 0
    total_pnl = 0
    hold_times = []
    trade_values = []

    for sym, ts in by_symbol.items():
        ts_sorted = sorted(ts, key=lambda x: x.get("time",""))
        for i in range(0, len(ts_sorted)-1, 2):
            if i+1 >= len(ts_sorted):
                break
            b = ts_sorted[i]
            s = ts_sorted[i+1]
            if b.get("side","").upper() != "BUY":
                continue
            buy_price = float(b.get("price", 0))
            sell_price = float(s.get("price", 0))
            qty = int(b.get("qty", 0))
            if buy_price <= 0 or qty <= 0:
                continue
            pnl = (sell_price - buy_price) * qty
            pnl_pct = (sell_price / buy_price - 1) * 100
            total_pnl += pnl
            if pnl > 0:
                win_trades += 1
            else:
                loss_trades += 1

            # 持仓时间
            try:
                bt = datetime.strptime(b.get("time","")[:19], "%Y-%m-%d %H:%M:%S")
                st = datetime.strptime(s.get("time","")[:19], "%Y-%m-%d %H:%M:%S")
                hold_days = (st - bt).days
                hold_times.append(hold_days)
            except:
                pass
            trade_values.append(buy_price * qty)

    total_trades = win_trades + loss_trades
    win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0

    stats = {
        "total_trades": total_trades,
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_hold_days": round(np.mean(hold_times), 1) if hold_times else 0,
        "max_hold_days": int(np.max(hold_times)) if hold_times else 0,
        "min_hold_days": int(np.min(hold_times)) if hold_times else 0,
        "avg_trade_value": round(np.mean(trade_values), 0) if trade_values else 0,
        "current_positions": len({t.get("symbol") for t in trades if t.get("side","").upper() == "BUY"}) - len({t.get("symbol") for t in trades if t.get("side","").upper() == "SELL"}),
    }

    # 盈亏比
    if loss_trades > 0 and win_trades > 0:
        avg_win = total_pnl * (win_rate / 100) / win_trades if win_trades > 0 else 0
        avg_loss = abs(total_pnl * (1 - win_rate / 100) / loss_trades) if loss_trades > 0 else 1
        stats["profit_loss_ratio"] = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0
    else:
        stats["profit_loss_ratio"] = 0

    return stats


# ===== 2. 因子贡献分解 =====

def compute_factor_contribution(weighted_ic: dict = None) -> dict:
    """
    因子贡献分解。
    使用最近一次因子学习中的加权IC × 当前权重，
    估算每个因子对预期收益的贡献占比。
    """
    # 读取最近的进化记录
    evolution_file = "config/factor_evolution.json"
    if os.path.exists(evolution_file):
        with open(evolution_file) as f:
            history = json.load(f)
        if history:
            latest = history[-1]
            ic = latest.get("weighted_ic", {})
            weights = latest.get("new_weights", {})
        else:
            ic, weights = {}, {}
    else:
        # 读权重文件
        weights_file = "config/factor_weights.json"
        if os.path.exists(weights_file):
            with open(weights_file) as f:
                weights = json.load(f)
        else:
            weights = {"momentum": 45, "quality": 25, "trend": 15, "value": 8, "lowvol": 7}
        ic = {}

    if not ic:
        # 没有进化记录，用默认IC
        ic = {"momentum": 0.03, "quality": 0.15, "trend": 0.04, "lowvol": 0, "value": 0}

    factors = {"momentum": "动量", "quality": "质量", "trend": "趋势", "value": "价值", "lowvol": "低波"}
    total_w = sum(weights.values()) or 100

    contributions = []
    total_contrib = 0
    for k, cn in factors.items():
        w = weights.get(k, 0) / total_w
        ic_val = abs(ic.get(k, 0))
        contrib = w * ic_val
        total_contrib += contrib
        contributions.append({
            "key": k,
            "name": cn,
            "weight": weights.get(k, 0),
            "ic": round(ic_val, 4),
            "contribution": round(contrib, 4),
        })

    # 归一化
    if total_contrib > 0:
        for c in contributions:
            c["pct"] = round(c["contribution"] / total_contrib * 100, 1)
    else:
        for c in contributions:
            c["pct"] = 0

    contributions.sort(key=lambda x: -x["pct"])

    return {
        "factors": contributions,
        "total_weight": total_w,
        "estimated_monthly_return": round(total_contrib, 4),
    }


# ===== 3. 汇总报告 =====

def generate_report() -> dict:
    """生成完整绩效报告"""
    trades = load_trades()
    trade_stats = compute_trade_stats(trades)
    factor_contrib = compute_factor_contribution()

    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trade_stats": trade_stats,
        "factor_contribution": factor_contrib,
    }

    # 缓存
    with open(PERF_CACHE, "w") as f:
        json.dump(report, f, indent=2)

    return report


def print_report(report: dict = None):
    """终端打印报告"""
    if report is None:
        report = generate_report()

    ts = report.get("trade_stats", {})
    fc = report.get("factor_contribution", {})

    print(f"\n{'='*55}")
    print(f"  📊 绩效归因报告")
    print(f"  {report.get('time','')}")
    print(f"{'='*55}")

    print(f"\n📝 交易统计:")
    print(f"  总交易: {ts.get('total_trades',0)}笔")
    print(f"  胜率: {ts.get('win_rate',0):.1f}%")
    print(f"  盈亏比: {ts.get('profit_loss_ratio',0):.2f}")
    print(f"  总PnL: ${ts.get('total_pnl',0):.2f}")
    print(f"  平均持仓: {ts.get('avg_hold_days',0):.1f}天")
    if ts.get('win_trades',0) > 0:
        print(f"  盈利: {ts['win_trades']}笔 亏损: {ts['loss_trades']}笔")

    print(f"\n🧬 因子贡献分解:")
    print(f"{'因子':<8} {'权重':>6} {'IC':>8} {'贡献%':>8}")
    print(f"{'-'*35}")
    for f in fc.get("factors", []):
        print(f"  {f['name']:<6} {f['weight']:>5}% {f['ic']:>+8.4f} {f['pct']:>7.1f}%")
    print(f"{'-'*35}")

    if fc.get("estimated_monthly_return"):
        print(f"  预期月收益: {fc['estimated_monthly_return']:+.4f}")

    print(f"\n{'='*55}")


# ===== Web API 兼容 =====

def get_stats() -> dict:
    """Web面板 API 调用"""
    if os.path.exists(PERF_CACHE):
        with open(PERF_CACHE) as f:
            cache = json.load(f)
        t_str = cache.get("time","2026-01-01 00:00")[:19]
        if len(t_str) == 16: t_str += ":00"
        cache_age = (datetime.now() - datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")).seconds
        if cache_age < 300:  # 5分钟内缓存有效
            return cache
    return generate_report()


if __name__ == "__main__":
    if "--json" in sys.argv:
        import json as _json
        report = generate_report()
        print(_json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report()
