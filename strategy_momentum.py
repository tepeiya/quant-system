"""
动量激进策略 v1 — 与保守策略完全独立
===================================
特点：
- 纯动量选股（不依赖质量因子/趋势因子）
- 不择时（始终满仓）
- 高换手率（每周调仓）
- 15 只持仓，充分分散
- 止损更紧，止盈更松

独立性：
  1. 独立的策略逻辑文件
  2. 独立的信号输出文件（signals/signal_momentum_*.json）
  3. 独立的执行文件（paper_trader_momentum.py）
  4. daemon.py 中独立流程调用

回测接口：与 strategy_vector.py 相同的价格矩阵格式
"""

import numpy as np
import pandas as pd
import logging
import json
import os
from datetime import datetime, timedelta

logger = logging.getLogger("quant.strategy_momentum")

OUTPUT_DIR = "signals"


def run_momentum_strategy(prices: dict[str, pd.DataFrame],
                           spy: pd.DataFrame = None,
                           start: str = "2020-01-01",
                           end: str = None) -> dict:
    """
    纯动量激进策略——完整回测
    - 每月初选股
    - 12-1月动量排名前 20 只
    - 等权持有
    - 无大盘择时，始终满仓
    - 简单止损 -15%，无其他退出条件
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    dates = pd.bdate_range(start, end, freq="W")  # 周线
    T = len(dates)

    tickers = sorted(prices.keys())
    n = len(tickers)

    logger.info(f"动量策略: {n}只股票, {T}个交易周")

    # 价格矩阵
    P = np.full((T, n), np.nan)
    M = np.full((T, n), np.nan)  # 12-1月动量

    for j, ticker in enumerate(tickers):
        df = prices[ticker]
        if df is None or len(df) < 50:
            continue
        df_index = df.index
        if hasattr(df_index, 'tz') and df_index.tz is not None:
            df_index = df_index.tz_localize(None)
        for i, d in enumerate(dates):
            idx = df_index.get_indexer([d], method="nearest")
            if idx[0] < 0 or idx[0] >= len(df):
                continue
            row = df.iloc[idx[0]]
            P[i, j] = row["Close"]
            M[i, j] = row.get("Momentum_12M", row.get("Momentum_6M", np.nan))

    # 每月第一个交易日选股
    monthly_dates = pd.bdate_range(start, end, freq="MS")  # 月初
    monthly_idx = []
    for md in monthly_dates:
        idx = dates.get_indexer([md], method="bfill")
        if idx[0] >= 0 and idx[0] < T:
            monthly_idx.append(idx[0])
    monthly_idx = sorted(set(monthly_idx))

    # 回测
    from system_config import load as load_cfg
    cfg = load_cfg()

    max_pos = 15  # 15 只
    stop_loss = 0.15  # 简单 15% 止损
    cash = 100_000
    shares = np.zeros(n, dtype=int)
    entry_prices = np.zeros(n)
    peak_prices = np.zeros(n)

    equity_curve = np.full(T, np.nan)
    monthly_signals = {}  # 记录选股信号

    rebalance_months = set()

    for i in range(1, T):
        # 继承上期持仓
        if i > 1:
            shares_prev = shares.copy()
            entry_prices_prev = entry_prices.copy()
        else:
            shares_prev = shares.copy()
            entry_prices_prev = entry_prices.copy()

        # 检查止损（每次迭代）
        for j in range(n):
            if shares[j] <= 0 or entry_prices[j] <= 0:
                continue
            cur_p = P[i, j]
            if np.isnan(cur_p):
                shares[j] = 0
                entry_prices[j] = 0
                continue
            pnl = (cur_p - entry_prices[j]) / entry_prices[j]
            # 更新最高价
            peak_prices[j] = max(peak_prices[j], cur_p)
            # 跟踪止损：从最高点回落 12%
            if peak_prices[j] > entry_prices[j] * 1.05:
                if cur_p < peak_prices[j] * 0.88:
                    cash += shares[j] * cur_p
                    shares[j] = 0
                    entry_prices[j] = 0
                    continue
            # 简单止损
            if pnl < -stop_loss:
                cash += shares[j] * cur_p
                shares[j] = 0
                entry_prices[j] = 0

        # 每月调仓
        if i in monthly_idx:
            rebalance_months.add(i)
            # 动量排名
            mom_row = M[i]
            valid = ~np.isnan(mom_row)
            if valid.sum() < max_pos:
                # 不够股票就不调仓
                equity = cash + np.sum(shares * P[i])
                equity_curve[i] = equity
                continue

            ranks = pd.Series(mom_row[valid]).rank(ascending=False)
            # 选前 max_pos 只
            top_indices = np.where(valid)[0][ranks.values <= max_pos]
            target_tickers = [tickers[j] for j in top_indices]

            # 记录信号
            month_key = dates[i].strftime("%Y-%m")
            monthly_signals[month_key] = {
                "date": str(dates[i]),
                "tickers": target_tickers,
                "count": len(target_tickers),
                "avg_mom_rank": float(ranks[ranks.values <= max_pos].mean()),
            }

            # 计算当前持仓价值
            portfolio_value = cash + np.sum(shares * P[i])

            # 平掉不在目标池的持仓
            for j in range(n):
                if shares[j] > 0 and tickers[j] not in target_tickers:
                    cash += shares[j] * P[i, j]
                    shares[j] = 0
                    entry_prices[j] = 0
                    peak_prices[j] = 0

            # [升级] 动量加权买入（不是等权）
            mom_scores = np.array([mom_row[tickers.index(tkr)] if tickers.index(tkr) < len(mom_row) else 0
                                    for tkr in target_tickers])
            mom_scores = np.maximum(mom_scores, 0.01)
            total_mom = np.sum(mom_scores) if np.sum(mom_scores) > 0 else len(target_tickers)
            for idx, tkr in enumerate(target_tickers):
                j = tickers.index(tkr)
                if shares[j] > 0:
                    continue
                price = P[i, j]
                if np.isnan(price) or price <= 0:
                    continue
                # 动量越强仓位越大
                weight = mom_scores[idx] / total_mom if total_mom > 0 else 1.0 / len(target_tickers)
                alloc = portfolio_value * 0.95 * weight
                qty = int(alloc / price)
                cost = qty * price
                if cost > cash:
                    qty = int(cash / price)
                    cost = qty * price
                if qty > 0:
                    shares[j] = qty
                    entry_prices[j] = price
                    peak_prices[j] = price
                    cash -= cost

        # 记录权益
        equity = cash + np.sum(shares * P[i])
        equity_curve[i] = equity

    # 计算回测指标
    valid_equity = equity_curve[~np.isnan(equity_curve)]
    if len(valid_equity) < 2:
        return {"error": "回测数据不足"}

    total_return = (valid_equity[-1] / valid_equity[0] - 1) * 100
    years = len(valid_equity) / 52
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 最大回撤
    peak = np.maximum.accumulate(valid_equity)
    drawdown = (valid_equity - peak) / peak * 100
    max_dd = drawdown.min()

    # 夏普（假设无风险 2%）
    daily_returns = np.diff(valid_equity) / valid_equity[:-1]
    excess = daily_returns - 0.02 / 252
    sharpe = np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0

    result = {
        "strategy": "momentum_aggressive",
        "total_return_pct": round(total_return, 2),
        "annual_return_pct": round(annual_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "stock_count": n,
        "period": {"start": str(dates[0]), "end": str(dates[-1])},
        "avg_monthly_positions": max_pos,
    }

    # 保存最新信号
    if monthly_signals:
        latest_month = sorted(monthly_signals.keys())[-1]
        latest_signal = monthly_signals[latest_month]
        signal_file = f"{OUTPUT_DIR}/signal_momentum.json"
        with open(signal_file, "w") as f:
            json.dump({
                "strategy": "momentum_aggressive",
                "date": str(datetime.now()),
                "rebalance_date": latest_signal["date"],
                "tickers": latest_signal["tickers"],
                "count": latest_signal["count"],
            }, f, indent=2)
        logger.info(f"信号已保存: {signal_file} ({latest_signal['count']}只)")

    return result


def generate_signals(prices: dict[str, pd.DataFrame], top_n: int = 15) -> list[str]:
    """
    快速生成最新信号（不跑完整回测）
    - 基于最近 12 月动量排名
    - 返回 top_n 只股票代码
    """
    tickers = sorted(prices.keys())
    mom_scores = []

    for tkr in tickers:
        df = prices[tkr]
        if df is None or len(df) < 252:
            continue
        close = df["Close"].values
        # 12月动量
        mom_12m = (close[-1] - close[-252]) / close[-252] if len(close) >= 252 else 0
        # 6月动量
        mom_6m = (close[-1] - close[-126]) / close[-126] if len(close) >= 126 else mom_12m
        # 3月动量
        mom_3m = (close[-1] - close[-63]) / close[-63] if len(close) >= 63 else mom_6m
        # 综合得分（12月权重最大）
        score = mom_12m * 0.5 + mom_6m * 0.3 + mom_3m * 0.2
        mom_scores.append((tkr, score))

    mom_scores.sort(key=lambda x: x[1], reverse=True)
    top_tickers = [t for t, s in mom_scores[:top_n]]

    # 保存信号
    signal_file = f"{OUTPUT_DIR}/signal_momentum.json"
    signal_data = {
        "strategy": "momentum_aggressive",
        "date": str(datetime.now()),
        "tickers": top_tickers,
        "count": len(top_tickers),
    }
    with open(signal_file, "w") as f:
        json.dump(signal_data, f, indent=2)
    logger.info(f"动量信号: {len(top_tickers)}只 → {signal_file}")

    # === 写入信号总线 ===
    try:
        import signal_bus
        candidates = [{"ticker": t, "score": round(1 - i/len(top_tickers), 3)} for i, t in enumerate(top_tickers[:10])]
        signal_bus.write_signal("momentum", candidates,
                                buy_list=top_tickers,
                                metadata={"signal_file": signal_file})
        logger.info("  ✅ 已写入信号总线")
    except Exception as e:
        logger.debug(f"  信号总线写入失败(不影响): {e}")

    return top_tickers


def backtest():
    """独立回测入口"""
    from data_prod import load_price_cache, compute_indicators

    logger.info("加载缓存数据...")
    cache = load_price_cache()
    logger.info(f"缓存: {len(cache)}只")

    # 确保技术指标已计算
    for tkr in list(cache.keys()):
        df = cache[tkr]
        if df is not None and "Momentum_12M" not in df.columns:
            cache[tkr] = compute_indicators(df)

    result = run_momentum_strategy(cache)

    print("\n" + "=" * 55)
    print("  📊 动量激进策略回测结果")
    print("=" * 55)
    print(f"  总收益:      {result.get('total_return_pct', 0):+.2f}%")
    print(f"  年化收益:    {result.get('annual_return_pct', 0):+.2f}%")
    print(f"  最大回撤:    {result.get('max_drawdown_pct', 0):+.2f}%")
    print(f"  夏普比率:    {result.get('sharpe_ratio', 0):.2f}")
    print(f"  股票数量:    {result.get('stock_count', 0)}")
    print(f"  周期:        {result.get('period', {}).get('start')} ~ {result.get('period', {}).get('end')}")
    print("=" * 55)

    # 与保守策略对比
    try:
        with open(f"{OUTPUT_DIR}/backtest_report.json") as f:
            conservative = json.load(f)
        print(f"\n对比保守策略:")
        print(f"  保守: +{conservative.get('strategy',{}).get('total_return_pct',0):.1f}% / 回撤 {conservative.get('strategy',{}).get('max_drawdown_pct',0):.1f}%")
        print(f"  激进: +{result.get('total_return_pct',0):.1f}% / 回撤 {result.get('max_drawdown_pct',0):.1f}%")
    except:
        pass

    return result


if __name__ == "__main__":
    import logging, sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    if "--generate" in sys.argv:
        # 只生成最新信号（daemon 调用）
        from data_prod import load_price_cache, compute_indicators
        cache = load_price_cache()
        for tkr in list(cache.keys()):
            df = cache[tkr]
            if df is not None and "Momentum_12M" not in df.columns:
                cache[tkr] = compute_indicators(df)
        generate_signals(cache, top_n=15)
    else:
        backtest()
