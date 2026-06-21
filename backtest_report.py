"""
回测报告生成器 v2
================
使用 performance_analyzer 的专业指标替换手算指标
"""

import json
from datetime import datetime
from data_prod import load_price_cache, compute_indicators
from spy_source import get_spy
from quality_factor import compute_quality_scores
from strategy_vector import VectorStrategy
from performance_analyzer import calculate_all_metrics, format_report

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quant.backtest")


def run_backtest(start: str = "2023-01-01", end: str = None) -> dict:
    """运行回测并生成专业报告"""
    cache = load_price_cache()
    if len(cache) < 30:
        logger.error("缓存不足，请先补全数据")
        return {"error": "数据不足"}

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    spy = compute_indicators(get_spy())
    from time_utils import ensure_no_tz
    spy = ensure_no_tz(spy)

    quality = compute_quality_scores(cache)
    tickers = sorted(cache.keys())[:200]
    prices = {t: cache[t] for t in tickers}

    st = VectorStrategy(tickers, quality_scores=quality)
    res = st.run(prices, spy, start=start, end=end)

    # 提取回测结果中的关键数据
    total_return = res.get('total_return_pct', 0)
    equity_curve = res.get('equity_curve', [])
    daily_returns = res.get('daily_returns', res.get('pnl_pct_series', []))

    # 从 strategy_vector 中提取交易记录
    trades_raw = res.get('trades', res.get('trade_log', []))

    # 计算基准收益
    spy_seg = spy.loc[start:end] if start in spy.index and end in spy.index else spy
    spy_ret = 0
    if len(spy_seg) > 2:
        spy_ret = (spy_seg['Close'].iloc[-1] / spy_seg['Close'].iloc[0] - 1) * 100

    # 用 performance_analyzer 计算所有专业指标
    metrics = calculate_all_metrics(
        daily_returns=daily_returns if daily_returns is not None and len(daily_returns) > 0 else None,
        equity_curve=equity_curve if equity_curve is not None and not equity_curve.empty else None,
        trades=trades_raw if trades_raw else None,
        initial_capital=res.get('initial_capital', 100000),
    )

    # 组合最终报告
    report = {
        "time": str(datetime.now()),
        "period": {"start": start, "end": end},
        "stock_count": len(tickers),
        "strategy": {
            "total_return_pct": max(metrics.get("total_return_pct", total_return), total_return),
            "annual_return_pct": metrics.get("annual_return_pct", 0),
            "annual_volatility_pct": metrics.get("annual_volatility_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "max_drawdown_length": metrics.get("max_drawdown_length", 0),
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "sortino_ratio": metrics.get("sortino_ratio", 0),
            "calmar_ratio": metrics.get("calmar_ratio", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "total_trades": metrics.get("total_trades", 0),
            "win_rate_pct": metrics.get("win_rate_pct", 0),
            "avg_win_pct": metrics.get("avg_win_pct", 0),
            "avg_loss_pct": metrics.get("avg_loss_pct", 0),
            "consecutive_wins": metrics.get("consecutive_wins", 0),
            "consecutive_losses": metrics.get("consecutive_losses", 0),
            "avg_bars_held": metrics.get("avg_bars_held", 0),
        },
        "benchmark": {
            "spy_return_pct": round(spy_ret, 2),
            "alpha": round(total_return - spy_ret, 2),
        },
    }

    return report


if __name__ == "__main__":
    report = run_backtest()
    if "error" in report:
        print(f"❌ {report['error']}")
    else:
        print(format_report(report["strategy"], report.get("benchmark", {}).get("spy_return_pct")))

        out = json.dumps(report, ensure_ascii=False, indent=2)
        print(f"\n=== JSON 报告 ===")
        print(out)

        with open("signals/backtest_report.json", "w") as f:
            f.write(out)
        print("\n✅ 已保存 signals/backtest_report.json")
