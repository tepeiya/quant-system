"""
回测归因分析模块 (Backtest Attribution Analysis)
===============================================
基于 Vibe-Trading 的分层归因体系

分析维度：
1. 交易级归因 - 盈利/亏损交易分析
2. 因子贡献 - 各因子对收益的贡献度
3. 市场归因 - Beta回归分析
4. 市场状态分析 - 不同市场状态下的表现
5. Monte Carlo检验 - 统计显著性检验

设计原则：
- 标准化输出格式
- 支持多种回测结果格式
- 可视化友好
"""

import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from scipy import stats

logger = logging.getLogger("quant.attribution")


# ============================================================
# 交易级归因
# ============================================================

def analyze_trade_level(trades: List[Dict]) -> Dict:
    """交易级归因分析"""
    if not trades:
        return {}
    
    df = pd.DataFrame(trades)
    
    profit_trades = df[df["pnl"] > 0]
    loss_trades = df[df["pnl"] <= 0]
    
    return {
        "total_trades": len(df),
        "win_count": len(profit_trades),
        "loss_count": len(loss_trades),
        "win_rate": len(profit_trades) / len(df) if len(df) > 0 else 0,
        
        "total_pnl": float(df["pnl"].sum()),
        "avg_win": float(profit_trades["pnl"].mean()) if len(profit_trades) > 0 else 0,
        "avg_loss": float(loss_trades["pnl"].mean()) if len(loss_trades) > 0 else 0,
        "profit_factor": abs(float(profit_trades["pnl"].sum() / loss_trades["pnl"].sum())) if len(loss_trades) > 0 and loss_trades["pnl"].sum() != 0 else np.inf,
        
        "best_trade": float(df["pnl"].max()),
        "worst_trade": float(df["pnl"].min()),
        
        "avg_holding_days": float(df.get("holding_days", pd.Series(0)).mean()),
        
        "max_consecutive_wins": _max_consecutive(df["pnl"] > 0),
        "max_consecutive_losses": _max_consecutive(df["pnl"] <= 0),
    }


def _max_consecutive(series: pd.Series) -> int:
    """计算最大连续次数"""
    if len(series) == 0:
        return 0
    max_count = 0
    current = 0
    for val in series:
        if val:
            current += 1
            max_count = max(max_count, current)
        else:
            current = 0
    return max_count


# ============================================================
# 因子贡献分析
# ============================================================

def analyze_factor_contribution(factors: pd.DataFrame, returns: pd.Series) -> Dict:
    """因子贡献分析（线性回归）"""
    if factors is None or returns is None or len(factors) == 0:
        return {}
    
    combined = pd.DataFrame({"return": returns}).join(factors).dropna()
    
    if len(combined) < 10:
        return {}
    
    try:
        X = combined.drop("return", axis=1)
        y = combined["return"]
        
        from sklearn.linear_model import LinearRegression
        model = LinearRegression()
        model.fit(X, y)
        
        contributions = dict(zip(X.columns, model.coef_))
        r_squared = model.score(X, y)
        
        return {
            "r_squared": float(r_squared),
            "intercept": float(model.intercept_),
            "contributions": {k: float(v) for k, v in contributions.items()},
            "sorted_contributions": sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True),
        }
    except ImportError:
        logger.warning("sklearn未安装，跳过因子贡献分析")
        return {}
    except Exception as e:
        logger.warning(f"因子贡献分析失败: {e}")
        return {}


# ============================================================
# Beta回归分析
# ============================================================

def analyze_beta_regression(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> Dict:
    """Beta回归分析"""
    if len(strategy_returns) == 0 or len(benchmark_returns) == 0:
        return {}
    
    combined = pd.DataFrame({
        "strategy": strategy_returns,
        "benchmark": benchmark_returns
    }).dropna()
    
    if len(combined) < 10:
        return {}
    
    try:
        X = combined["benchmark"].values.reshape(-1, 1)
        y = combined["strategy"].values
        
        slope, intercept, r_value, p_value, std_err = stats.linregress(X.flatten(), y)
        
        alpha = intercept
        beta = slope
        sharpe_ratio = (y.mean() / y.std()) * np.sqrt(252) if y.std() > 0 else 0
        treynor_ratio = (y.mean() / beta) if beta != 0 else 0
        information_ratio = ((y - X.flatten()).mean() / (y - X.flatten()).std()) * np.sqrt(252) if (y - X.flatten()).std() > 0 else 0
        
        return {
            "beta": float(beta),
            "alpha": float(alpha),
            "r_squared": float(r_value ** 2),
            "p_value": float(p_value),
            "std_err": float(std_err),
            "sharpe_ratio": float(sharpe_ratio),
            "treynor_ratio": float(treynor_ratio),
            "information_ratio": float(information_ratio),
            "excess_return": float((y - X.flatten()).mean()),
        }
    except Exception as e:
        logger.warning(f"Beta回归分析失败: {e}")
        return {}


# ============================================================
# 市场状态分析
# ============================================================

def analyze_market_regimes(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> Dict:
    """市场状态分析"""
    if len(strategy_returns) == 0 or len(benchmark_returns) == 0:
        return {}
    
    combined = pd.DataFrame({
        "strategy": strategy_returns,
        "benchmark": benchmark_returns
    }).dropna()
    
    if len(combined) < 20:
        return {}
    
    regime_definitions = {
        "bull": combined["benchmark"] > combined["benchmark"].rolling(60).mean() * 1.02,
        "bear": combined["benchmark"] < combined["benchmark"].rolling(60).mean() * 0.98,
        "sideways": ~(combined["benchmark"] > combined["benchmark"].rolling(60).mean() * 1.02) & 
                    ~(combined["benchmark"] < combined["benchmark"].rolling(60).mean() * 0.98),
    }
    
    results = {}
    for regime, mask in regime_definitions.items():
        regime_returns = combined[mask]["strategy"]
        if len(regime_returns) > 5:
            results[regime] = {
                "days": len(regime_returns),
                "avg_return": float(regime_returns.mean()),
                "std_return": float(regime_returns.std()),
                "sharpe": float((regime_returns.mean() / regime_returns.std()) * np.sqrt(252)) if regime_returns.std() > 0 else 0,
                "positive_days": float((regime_returns > 0).mean()),
            }
    
    return results


# ============================================================
# Monte Carlo 检验
# ============================================================

def monte_carlo_test(strategy_returns: pd.Series, num_simulations: int = 1000) -> Dict:
    """Monte Carlo检验"""
    if len(strategy_returns) == 0:
        return {}
    
    actual_total = strategy_returns.sum()
    actual_sharpe = (strategy_returns.mean() / strategy_returns.std()) * np.sqrt(252) if strategy_returns.std() > 0 else 0
    
    simulated_totals = []
    simulated_sharpes = []
    
    for _ in range(num_simulations):
        shuffled = strategy_returns.sample(frac=1).reset_index(drop=True)
        simulated_totals.append(shuffled.sum())
        if shuffled.std() > 0:
            simulated_sharpes.append((shuffled.mean() / shuffled.std()) * np.sqrt(252))
    
    p_value_total = sum(1 for t in simulated_totals if t >= actual_total) / num_simulations
    p_value_sharpe = sum(1 for s in simulated_sharpes if s >= actual_sharpe) / num_simulations
    
    return {
        "actual_total_return": float(actual_total),
        "actual_sharpe_ratio": float(actual_sharpe),
        "simulation_count": num_simulations,
        "p_value_total": float(p_value_total),
        "p_value_sharpe": float(p_value_sharpe),
        "significant": p_value_total < 0.05,
        "simulated_mean_total": float(np.mean(simulated_totals)),
        "simulated_std_total": float(np.std(simulated_totals)),
    }


# ============================================================
# 综合归因分析
# ============================================================

def analyze_backtest(backtest_result: Dict) -> Dict:
    """综合归因分析"""
    result = {
        "trade_level": {},
        "factor_contribution": {},
        "beta_regression": {},
        "market_regimes": {},
        "monte_carlo": {},
        "summary": {},
    }
    
    trades = backtest_result.get("trades", [])
    if trades:
        result["trade_level"] = analyze_trade_level(trades)
    
    factors = backtest_result.get("factors")
    returns = backtest_result.get("returns")
    if factors and returns:
        if isinstance(factors, pd.DataFrame):
            factors_df = factors
        elif isinstance(factors, dict):
            factors_df = pd.DataFrame(factors)
        else:
            factors_df = None
        
        if isinstance(returns, pd.Series):
            returns_series = returns
        elif isinstance(returns, list):
            returns_series = pd.Series(returns)
        else:
            returns_series = None
        
        if factors_df is not None and returns_series is not None:
            result["factor_contribution"] = analyze_factor_contribution(factors_df, returns_series)
    
    strategy_returns = backtest_result.get("strategy_returns")
    benchmark_returns = backtest_result.get("benchmark_returns")
    if strategy_returns and benchmark_returns:
        if isinstance(strategy_returns, pd.Series):
            strat_series = strategy_returns
        elif isinstance(strategy_returns, list):
            strat_series = pd.Series(strategy_returns)
        else:
            strat_series = None
        
        if isinstance(benchmark_returns, pd.Series):
            bench_series = benchmark_returns
        elif isinstance(benchmark_returns, list):
            bench_series = pd.Series(benchmark_returns)
        else:
            bench_series = None
        
        if strat_series is not None:
            result["monte_carlo"] = monte_carlo_test(strat_series)
        
        if strat_series is not None and bench_series is not None:
            result["beta_regression"] = analyze_beta_regression(strat_series, bench_series)
            result["market_regimes"] = analyze_market_regimes(strat_series, bench_series)
    
    result["summary"] = _generate_summary(result)
    
    return result


def _generate_summary(attribution: Dict) -> Dict:
    """生成归因摘要"""
    trade_level = attribution.get("trade_level", {})
    beta_reg = attribution.get("beta_regression", {})
    mc = attribution.get("monte_carlo", {})
    
    summary = {
        "total_trades": trade_level.get("total_trades", 0),
        "win_rate": trade_level.get("win_rate", 0),
        "profit_factor": trade_level.get("profit_factor", 0),
        "beta": beta_reg.get("beta", 0),
        "alpha": beta_reg.get("alpha", 0),
        "sharpe_ratio": beta_reg.get("sharpe_ratio", 0),
        "statistically_significant": mc.get("significant", False),
    }
    
    return summary


# ============================================================
# 便捷函数
# ============================================================

def load_backtest_results(file_path: str) -> Dict:
    """加载回测结果文件"""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"加载回测结果失败: {e}")
        return {}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="回测归因分析")
    parser.add_argument("--file", default="signals/backtest_report.json", help="回测结果文件")
    args = parser.parse_args()
    
    print("加载回测结果...")
    backtest = load_backtest_results(args.file)
    
    if backtest:
        print("执行归因分析...")
        attribution = analyze_backtest(backtest)
        
        print("\n" + "="*50)
        print("归因分析报告")
        print("="*50)
        
        if attribution["trade_level"]:
            tl = attribution["trade_level"]
            print(f"\n【交易级分析】")
            print(f"  总交易数: {tl['total_trades']}")
            print(f"  胜率: {tl['win_rate']:.2%}")
            print(f"  平均盈利: {tl['avg_win']:.2f}")
            print(f"  平均亏损: {tl['avg_loss']:.2f}")
            print(f"  盈亏比: {tl['profit_factor']:.2f}")
        
        if attribution["beta_regression"]:
            br = attribution["beta_regression"]
            print(f"\n【Beta回归】")
            print(f"  Beta: {br['beta']:.2f}")
            print(f"  Alpha: {br['alpha']:.4f}")
            print(f"  R²: {br['r_squared']:.2f}")
            print(f"  Sharpe: {br['sharpe_ratio']:.2f}")
        
        if attribution["market_regimes"]:
            mr = attribution["market_regimes"]
            print(f"\n【市场状态分析】")
            for regime, stats_ in mr.items():
                print(f"  {regime}: 天数={stats_['days']}, 平均收益={stats_['avg_return']:.4f}, Sharpe={stats_['sharpe']:.2f}")
        
        if attribution["monte_carlo"]:
            mc = attribution["monte_carlo"]
            print(f"\n【Monte Carlo检验】")
            print(f"  实际总收益: {mc['actual_total_return']:.2f}")
            print(f"  实际Sharpe: {mc['actual_sharpe_ratio']:.2f}")
            print(f"  p-value(收益): {mc['p_value_total']:.4f}")
            print(f"  p-value(Sharpe): {mc['p_value_sharpe']:.4f}")
            print(f"  统计显著: {'是' if mc['significant'] else '否'}")
        
        if attribution["summary"]:
            summary = attribution["summary"]
            print(f"\n【摘要】")
            print(f"  统计显著: {'✅' if summary['statistically_significant'] else '❌'}")
    else:
        print("未找到回测结果文件")