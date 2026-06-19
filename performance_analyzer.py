"""
绩效分析模块 — 从 backtrader analyzers 提取的核心算法
===================================================
不依赖 backtrader 框架，独立函数，直接计算专业交易指标。

支持的指标：
  - 夏普比率 (Sharpe Ratio)
  - 卡玛比率 (Calmar Ratio)
  - 最大回撤 (Max Drawdown)
  - 交易分析 (Trade Analysis)
  - 年化收益/波动率
  - 索提诺比率 (Sortino Ratio)
  - 盈亏比 (Profit Factor)

用法：
  from performance_analyzer import calculate_all_metrics
  metrics = calculate_all_metrics(daily_returns, trades_df)
"""

import numpy as np
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger("quant.performance")


# ============================================================
# 夏普比率
# ============================================================
def sharpe_ratio(daily_returns: list, risk_free_rate: float = 0.01,
                 annual_factor: int = 252, annualize: bool = True) -> float:
    """
    计算夏普比率

    参数:
        daily_returns: 日收益率列表 (百分比形式，如 0.5 表示 0.5%)
        risk_free_rate: 年化无风险利率 (默认 1%)
        annual_factor: 年化因子 (日=252, 周=52, 月=12)
        annualize: 是否返回年化夏普

    返回:
        sharpe_ratio: 夏普比率
    """
    returns = np.array(daily_returns, dtype=float)
    if len(returns) < 2:
        return 0.0

    # 日化无风险利率
    daily_rf = pow(1.0 + risk_free_rate, 1.0 / annual_factor) - 1.0

    # 超额收益
    excess = returns - daily_rf
    avg_excess = np.mean(excess)
    std_excess = np.std(excess, ddof=1)  # 样本标准差

    if std_excess == 0:
        return 0.0

    ratio = avg_excess / std_excess

    if annualize:
        ratio = np.sqrt(annual_factor) * ratio

    return round(float(ratio), 4)


# ============================================================
# 索提诺比率 (只考虑下行波动)
# ============================================================
def sortino_ratio(daily_returns: list, risk_free_rate: float = 0.01,
                  annual_factor: int = 252) -> float:
    """
    计算索提诺比率 — 只惩罚下行波动

    参数:
        daily_returns: 日收益率列表
        risk_free_rate: 年化无风险利率
        annual_factor: 年化因子

    返回:
        sortino_ratio: 索提诺比率
    """
    returns = np.array(daily_returns, dtype=float)
    if len(returns) < 2:
        return 0.0

    daily_rf = pow(1.0 + risk_free_rate, 1.0 / annual_factor) - 1.0
    excess = returns - daily_rf

    # 只计算下行标准差
    downside = excess[excess < 0]
    if len(downside) == 0:
        return np.inf if np.mean(excess) > 0 else 0.0

    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return 0.0

    ratio = np.mean(excess) / downside_std
    ratio = np.sqrt(annual_factor) * ratio

    return round(float(ratio), 4)


# ============================================================
# 最大回撤
# ============================================================
def max_drawdown(equity_curve: list) -> dict:
    """
    计算最大回撤及相关指标

    参数:
        equity_curve: 净值序列 (如 [100000, 101000, 99000, ...])

    返回:
        dict: {max_drawdown_pct, max_drawdown_value, max_drawdown_length,
               drawdown_curve}
    """
    equity = np.array(equity_curve, dtype=float)
    if len(equity) < 2:
        return {"max_drawdown_pct": 0, "max_drawdown_value": 0,
                "max_drawdown_length": 0, "drawdown_curve": []}

    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak * 100
    drawdown_value = peak - equity

    max_dd_idx = np.argmax(drawdown)
    max_dd_pct = float(drawdown[max_dd_idx])
    max_dd_value = float(drawdown_value[max_dd_idx])

    # 回撤长度
    dd_lengths = []
    current_len = 0
    for dd in drawdown:
        if dd > 0:
            current_len += 1
        else:
            if current_len > 0:
                dd_lengths.append(current_len)
            current_len = 0
    if current_len > 0:
        dd_lengths.append(current_len)

    return {
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_value": round(max_dd_value, 2),
        "max_drawdown_length": max(dd_lengths) if dd_lengths else 0,
        "drawdown_curve": [round(float(x), 2) for x in drawdown],
    }


# ============================================================
# 卡玛比率
# ============================================================
def calmar_ratio(annual_return_pct: float, max_drawdown_pct: float) -> float:
    """
    计算卡玛比率 = 年化收益 / 最大回撤

    参数:
        annual_return_pct: 年化收益率 (%)
        max_drawdown_pct: 最大回撤 (%)

    返回:
        calmar_ratio: 卡玛比率
    """
    if max_drawdown_pct == 0:
        return 0.0
    return round(annual_return_pct / abs(max_drawdown_pct), 4)


# ============================================================
# 交易分析
# ============================================================
def trade_analysis(trades: list) -> dict:
    """
    交易分析 — 统计所有交易的表现

    参数:
        trades: 交易列表，每笔交易为 dict，包含:
            - pnl: 盈亏金额
            - pnl_pct: 盈亏百分比
            - side: 'BUY' 或 'SELL'
            - symbol: 股票代码
            - entry_time: 入场时间
            - exit_time: 出场时间

    返回:
        dict: 交易统计指标
    """
    if not trades or len(trades) == 0:
        return {
            "total_trades": 0, "won": 0, "lost": 0,
            "win_rate": 0, "profit_factor": 0,
            "avg_win": 0, "avg_loss": 0,
            "max_win": 0, "max_loss": 0,
            "avg_bars_held": 0,
            "consecutive_wins": 0, "consecutive_losses": 0,
        }

    pnls = np.array([t.get("pnl", 0) for t in trades])
    pnl_pcts = np.array([t.get("pnl_pct", 0) for t in trades])

    won = pnls[pnls > 0]
    lost = pnls[pnls < 0]
    total_won = len(won)
    total_lost = len(lost)

    win_rate = total_won / len(trades) * 100 if len(trades) > 0 else 0

    # 盈亏比 (Profit Factor)
    sum_won = abs(np.sum(won)) if len(won) > 0 else 0
    sum_lost = abs(np.sum(lost)) if len(lost) > 0 else 0
    profit_factor = sum_won / sum_lost if sum_lost > 0 else (np.inf if sum_won > 0 else 0)

    # 连续盈亏
    consecutive_wins = 0
    consecutive_losses = 0
    current_win_streak = 0
    current_loss_streak = 0
    for p in pnls:
        if p > 0:
            current_win_streak += 1
            current_loss_streak = 0
            consecutive_wins = max(consecutive_wins, current_win_streak)
        elif p < 0:
            current_loss_streak += 1
            current_win_streak = 0
            consecutive_losses = max(consecutive_losses, current_loss_streak)

    # 平均持仓时间
    avg_bars_held = 0
    if "entry_time" in trades[0] and "exit_time" in trades[0]:
        bars = []
        for t in trades:
            try:
                entry = pd.Timestamp(t["entry_time"])
                exit = pd.Timestamp(t["exit_time"])
                bars.append((exit - entry).days)
            except:
                pass
        if bars:
            avg_bars_held = np.mean(bars)

    return {
        "total_trades": len(trades),
        "won": int(total_won),
        "lost": int(total_lost),
        "win_rate_pct": round(float(win_rate), 2),
        "profit_factor": round(float(profit_factor), 4),
        "avg_win": round(float(np.mean(won)), 2) if len(won) > 0 else 0,
        "avg_loss": round(float(np.mean(lost)), 2) if len(lost) > 0 else 0,
        "max_win": round(float(np.max(won)), 2) if len(won) > 0 else 0,
        "max_loss": round(float(np.min(lost)), 2) if len(lost) > 0 else 0,
        "avg_win_pct": round(float(np.mean(pnl_pcts[pnl_pcts > 0])), 2) if len(won) > 0 else 0,
        "avg_loss_pct": round(float(np.mean(pnl_pcts[pnl_pcts < 0])), 2) if len(lost) > 0 else 0,
        "consecutive_wins": int(consecutive_wins),
        "consecutive_losses": int(consecutive_losses),
        "avg_bars_held": round(float(avg_bars_held), 1),
        "total_pnl": round(float(np.sum(pnls)), 2),
    }


# ============================================================
# 年化收益率
# ============================================================
def annual_return(daily_returns: list, annual_factor: int = 252) -> dict:
    """
    计算年化收益率和波动率

    参数:
        daily_returns: 日收益率列表 (%)
        annual_factor: 年化因子

    返回:
        dict: {annual_return_pct, annual_volatility_pct, daily_avg_return, daily_std}
    """
    returns = np.array(daily_returns, dtype=float)
    if len(returns) < 2:
        return {"annual_return_pct": 0, "annual_volatility_pct": 0,
                "daily_avg_return": 0, "daily_std": 0}

    # 复合年化收益率
    total_return = np.prod(1 + returns / 100) - 1
    n_days = len(returns)
    ann_return = (pow(1 + total_return, annual_factor / n_days) - 1) * 100

    # 年化波动率
    daily_std = np.std(returns, ddof=1)
    ann_vol = daily_std * np.sqrt(annual_factor)

    return {
        "annual_return_pct": round(float(ann_return), 2),
        "annual_volatility_pct": round(float(ann_vol), 2),
        "daily_avg_return": round(float(np.mean(returns)), 4),
        "daily_std": round(float(daily_std), 4),
        "total_return_pct": round(float(total_return * 100), 2),
    }


# ============================================================
# 一键计算所有指标
# ============================================================
def calculate_all_metrics(daily_returns: list = None,
                          equity_curve: list = None,
                          trades: list = None,
                          initial_capital: float = 100000,
                          risk_free_rate: float = 0.01) -> dict:
    """
    一键计算所有绩效指标

    参数:
        daily_returns: 日收益率列表 (%) — 可选
        equity_curve: 净值序列 — 可选
        trades: 交易列表 — 可选
        initial_capital: 初始资金
        risk_free_rate: 年化无风险利率

    返回:
        dict: 所有指标
    """
    result = {}

    # 从净值曲线推导日收益率（如果没有直接提供）
    if daily_returns is None and equity_curve is not None:
        eq = np.array(equity_curve, dtype=float)
        if len(eq) >= 2:
            daily_returns = [float((eq[i] - eq[i-1]) / eq[i-1] * 100)
                            for i in range(1, len(eq))]
        else:
            daily_returns = []

    if daily_returns is None:
        daily_returns = []

    # 年化收益/波动
    ann = annual_return(daily_returns)
    result.update(ann)

    # 最大回撤
    if equity_curve is not None and len(equity_curve) >= 2:
        dd = max_drawdown(equity_curve)
        result.update({
            "max_drawdown_pct": dd["max_drawdown_pct"],
            "max_drawdown_value": dd["max_drawdown_value"],
            "max_drawdown_length": dd["max_drawdown_length"],
        })
    else:
        result.update({"max_drawdown_pct": 0, "max_drawdown_value": 0,
                       "max_drawdown_length": 0})

    # 夏普比率
    if len(daily_returns) >= 5:
        result["sharpe_ratio"] = sharpe_ratio(daily_returns, risk_free_rate)
        result["sortino_ratio"] = sortino_ratio(daily_returns, risk_free_rate)
    else:
        result["sharpe_ratio"] = 0
        result["sortino_ratio"] = 0

    # 卡玛比率
    result["calmar_ratio"] = calmar_ratio(
        result.get("annual_return_pct", 0),
        result.get("max_drawdown_pct", 0))

    # 交易分析
    if trades is not None:
        ta = trade_analysis(trades)
        result.update(ta)
    else:
        result.update({"total_trades": 0})

    # 与基准对比
    result["initial_capital"] = initial_capital
    if equity_curve is not None and len(equity_curve) >= 2:
        result["final_equity"] = round(float(equity_curve[-1]), 2)

    return result


# ============================================================
# 输出格式化报告
# ============================================================
def format_report(metrics: dict, benchmark_return: float = None) -> str:
    """格式化输出报告文本"""
    lines = []
    lines.append("=" * 55)
    lines.append("  📊 绩效分析报告")
    lines.append("=" * 55)

    lines.append(f"\n  📈 收益")
    lines.append(f"    总收益:        {metrics.get('total_return_pct', 0):>+8.2f}%")
    lines.append(f"    年化收益:      {metrics.get('annual_return_pct', 0):>+8.2f}%")
    lines.append(f"    年化波动:      {metrics.get('annual_volatility_pct', 0):>8.2f}%")
    if benchmark_return is not None:
        alpha = metrics.get('total_return_pct', 0) - benchmark_return
        lines.append(f"    基准收益:      {benchmark_return:>+8.2f}%")
        lines.append(f"    Alpha:         {alpha:>+8.2f}%")

    lines.append(f"\n  🛡️ 风险")
    lines.append(f"    最大回撤:      {metrics.get('max_drawdown_pct', 0):>8.2f}%")
    lines.append(f"    回撤天数:      {metrics.get('max_drawdown_length', 0):>8}天")

    lines.append(f"\n  ⚖️ 风险调整收益")
    lines.append(f"    夏普比率:      {metrics.get('sharpe_ratio', 0):>8.4f}")
    lines.append(f"    索提诺比率:    {metrics.get('sortino_ratio', 0):>8.4f}")
    lines.append(f"    卡玛比率:      {metrics.get('calmar_ratio', 0):>8.4f}")

    trades = metrics.get('total_trades', 0)
    if trades > 0:
        lines.append(f"\n  📝 交易统计")
        lines.append(f"    总交易:        {trades}")
        lines.append(f"    胜率:          {metrics.get('win_rate_pct', 0):>7.1f}%")
        lines.append(f"    盈亏比:        {metrics.get('profit_factor', 0):>8.2f}")
        lines.append(f"    平均盈利:      ${metrics.get('avg_win', 0):>+8.2f}")
        lines.append(f"    平均亏损:      ${metrics.get('avg_loss', 0):>+8.2f}")
        lines.append(f"    最大盈利:      ${metrics.get('max_win', 0):>+8.2f}")
        lines.append(f"    最大亏损:      ${metrics.get('max_loss', 0):>+8.2f}")
        lines.append(f"    连赢次数:      {metrics.get('consecutive_wins', 0)}")
        lines.append(f"    连亏次数:      {metrics.get('consecutive_losses', 0)}")

    lines.append("\n" + "=" * 55)
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试数据
    np.random.seed(42)
    test_returns = np.random.normal(0.05, 0.8, 252)
    test_equity = [100000]
    for r in test_returns:
        test_equity.append(test_equity[-1] * (1 + r / 100))

    test_trades = [
        {"pnl": 150, "pnl_pct": 1.5, "side": "BUY", "symbol": "AAPL"},
        {"pnl": -80, "pnl_pct": -0.8, "side": "SELL", "symbol": "MSFT"},
        {"pnl": 200, "pnl_pct": 2.0, "side": "BUY", "symbol": "GOOGL"},
        {"pnl": 50, "pnl_pct": 0.5, "side": "BUY", "symbol": "NVDA"},
        {"pnl": -120, "pnl_pct": -1.2, "side": "SELL", "symbol": "AMD"},
    ]

    metrics = calculate_all_metrics(
        daily_returns=test_returns.tolist(),
        equity_curve=test_equity,
        trades=test_trades,
    )

    print(format_report(metrics))
