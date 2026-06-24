"""
风险指标计算模块
==================
提供专业的风险度量指标

包含:
1. VaR (风险价值) - 历史法/参数法/蒙特卡洛
2. CVaR (条件风险价值) - 尾部风险度量
3. 最大回撤分析
4. Beta和相关性分析
5. HHI集中度指数
6. Greeks计算 (期权)
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from scipy import stats

logger = logging.getLogger(__name__)


# ============================================================
# VaR/CVaR 计算
# ============================================================

def calculate_var_historical(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    历史法VaR计算
    
    Args:
        returns: 收益率数组
        confidence: 置信水平 (0.95 = 95%)
    
    Returns:
        VaR值 (负数表示损失)
    """
    if len(returns) == 0:
        return 0.0
    
    # 取置信水平对应的分位数
    var = np.percentile(returns, (1 - confidence) * 100)
    return var


def calculate_var_parametric(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    参数法VaR计算 (假设正态分布)
    
    Args:
        returns: 收益率数组
        confidence: 置信水平
    
    Returns:
        VaR值
    """
    if len(returns) == 0:
        return 0.0
    
    mu = np.mean(returns)
    sigma = np.std(returns)
    
    # 使用正态分布的分位数
    z_score = stats.norm.ppf(1 - confidence)
    var = mu + sigma * z_score
    
    return var


def calculate_var_monte_carlo(
    returns: np.ndarray,
    confidence: float = 0.95,
    n_simulations: int = 10000
) -> float:
    """
    蒙特卡洛VaR计算
    
    Args:
        returns: 历史收益率数组
        confidence: 置信水平
        n_simulations: 模拟次数
    
    Returns:
        VaR值
    """
    if len(returns) == 0:
        return 0.0
    
    mu = np.mean(returns)
    sigma = np.std(returns)
    
    # 模拟未来收益
    simulated_returns = np.random.normal(mu, sigma, n_simulations)
    
    # 取分位数
    var = np.percentile(simulated_returns, (1 - confidence) * 100)
    
    return var


def calculate_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    CVaR (条件风险价值 / Expected Shortfall)
    计算超过VaR的平均损失
    
    Args:
        returns: 收益率数组
        confidence: 置信水平
    
    Returns:
        CVaR值
    """
    if len(returns) == 0:
        return 0.0
    
    var = calculate_var_historical(returns, confidence)
    
    # 取所有低于VaR的收益（更差的情形）
    tail_returns = returns[returns <= var]
    
    if len(tail_returns) == 0:
        return var
    
    cvar = np.mean(tail_returns)
    return cvar


def calculate_var_all_methods(
    returns: np.ndarray,
    confidence: float = 0.95
) -> Dict[str, float]:
    """
    使用所有方法计算VaR
    
    Returns:
        包含历史法、参数法、蒙特卡洛VaR和CVaR的字典
    """
    return {
        "var_historical": calculate_var_historical(returns, confidence),
        "var_parametric": calculate_var_parametric(returns, confidence),
        "var_monte_carlo": calculate_var_monte_carlo(returns, confidence),
        "cvar": calculate_cvar(returns, confidence),
        "confidence": confidence,
    }


# ============================================================
# 回撤分析
# ============================================================

def calculate_drawdown(equity_curve: np.ndarray) -> Dict[str, float]:
    """
    计算回撤指标
    
    Args:
        equity_curve: 权益曲线数组
    
    Returns:
        包含最大回撤、当前回撤、回撤持续时间的字典
    """
    if len(equity_curve) == 0:
        return {"max_drawdown": 0, "current_drawdown": 0, "drawdown_duration": 0}
    
    # 计算运行最高点
    running_max = np.maximum.accumulate(equity_curve)
    
    # 计算回撤
    drawdown = (equity_curve - running_max) / running_max
    
    max_dd = drawdown.min()
    current_dd = drawdown[-1]
    
    # 计算最大回撤持续时间
    peak_idx = np.argmax(equity_curve[:np.argmin(drawdown) + 1])
    trough_idx = np.argmin(drawdown)
    dd_duration = trough_idx - peak_idx
    
    return {
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd * 100,
        "current_drawdown": current_dd,
        "current_drawdown_pct": current_dd * 100,
        "drawdown_duration": dd_duration,
        "peak_value": equity_curve[peak_idx] if peak_idx < len(equity_curve) else equity_curve[0],
        "trough_value": equity_curve[trough_idx] if trough_idx < len(equity_curve) else equity_curve[-1],
    }


def calculate_underwater_periods(equity_curve: np.ndarray) -> List[Tuple[int, int]]:
    """
    计算水下期（权益低于历史最高点的时期）
    
    Returns:
        水下期列表 [(开始索引, 结束索引)]
    """
    if len(equity_curve) == 0:
        return []
    
    running_max = np.maximum.accumulate(equity_curve)
    underwater = equity_curve < running_max
    
    periods = []
    start = None
    
    for i, is_underwater in enumerate(underwater):
        if is_underwater and start is None:
            start = i
        elif not is_underwater and start is not None:
            periods.append((start, i - 1))
            start = None
    
    if start is not None:
        periods.append((start, len(equity_curve) - 1))
    
    return periods


# ============================================================
# Beta和相关性分析
# ============================================================

def calculate_beta(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray
) -> float:
    """
    计算组合Beta
    
    Args:
        portfolio_returns: 组合收益率
        benchmark_returns: 基准收益率 (如SPY)
    
    Returns:
        Beta值
    """
    if len(portfolio_returns) == 0 or len(benchmark_returns) == 0:
        return 1.0
    
    # 确保长度一致
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    portfolio_returns = portfolio_returns[:min_len]
    benchmark_returns = benchmark_returns[:min_len]
    
    covariance = np.cov(portfolio_returns, benchmark_returns)[0, 1]
    benchmark_variance = np.var(benchmark_returns)
    
    if benchmark_variance == 0:
        return 1.0
    
    beta = covariance / benchmark_variance
    return beta


def calculate_correlation_matrix(
    returns_data: pd.DataFrame
) -> pd.DataFrame:
    """
    计算资产相关性矩阵
    
    Args:
        returns_data: 收益率DataFrame (列为各资产)
    
    Returns:
        相关性矩阵
    """
    return returns_data.corr()


def calculate_rolling_beta(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    window: int = 60
) -> np.ndarray:
    """
    计算滚动Beta
    
    Args:
        portfolio_returns: 组合收益率
        benchmark_returns: 基准收益率
        window: 滚动窗口大小
    
    Returns:
        滚动Beta数组
    """
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    
    if min_len < window:
        return np.array([calculate_beta(portfolio_returns, benchmark_returns)])
    
    rolling_betas = []
    
    for i in range(window, min_len + 1):
        port_window = portfolio_returns[i-window:i]
        bench_window = benchmark_returns[i-window:i]
        beta = calculate_beta(port_window, bench_window)
        rolling_betas.append(beta)
    
    return np.array(rolling_betas)


# ============================================================
# 集中度分析
# ============================================================

def calculate_hhi(weights: np.ndarray) -> float:
    """
    计算Herfindahl-Hirschman Index (HHI)
    衡量持仓集中度
    
    HHI = sum(weight_i^2)
    - HHI < 0.15: 低集中度
    - 0.15 < HHI < 0.25: 中等集中度
    - HHI > 0.25: 高集中度
    
    Args:
        weights: 权重数组
    
    Returns:
        HHI值
    """
    if len(weights) == 0:
        return 0.0
    
    hhi = np.sum(weights ** 2)
    return hhi


def classify_concentration(hhi: float) -> str:
    """
    根据HHI分类集中度
    
    Args:
        hhi: HHI值
    
    Returns:
        集中度分类
    """
    if hhi < 0.15:
        return "低集中度"
    elif hhi < 0.25:
        return "中等集中度"
    else:
        return "高集中度"


def calculate_effective_n(weights: np.ndarray) -> float:
    """
    计算有效持仓数量
    
    N_eff = 1 / HHI
    
    Args:
        weights: 权重数组
    
    Returns:
        有效持仓数
    """
    hhi = calculate_hhi(weights)
    
    if hhi == 0:
        return 0.0
    
    return 1.0 / hhi


# ============================================================
# 期权Greeks计算
# ============================================================

def calculate_delta(
    spot_price: float,
    strike_price: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float = 0.05,
    option_type: str = "call"
) -> float:
    """
    计算期权Delta (Black-Scholes)
    
    Args:
        spot_price: 标的价格
        strike_price: 行权价
        time_to_expiry: 到期时间 (年)
        volatility: 波动率
        risk_free_rate: 无风险利率
        option_type: "call" 或 "put"
    
    Returns:
        Delta值
    """
    from math import log, sqrt, exp
    
    if time_to_expiry <= 0:
        # 到期时
        if option_type == "call":
            return 1.0 if spot_price > strike_price else 0.0
        else:
            return -1.0 if spot_price < strike_price else 0.0
    
    # 计算d1和d2
    d1 = (log(spot_price / strike_price) + 
          (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / \
          (volatility * sqrt(time_to_expiry))
    
    # Delta = N(d1) for call, N(d1) - 1 for put
    if option_type == "call":
        delta = stats.norm.cdf(d1)
    else:
        delta = stats.norm.cdf(d1) - 1
    
    return delta


def calculate_gamma(
    spot_price: float,
    strike_price: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float = 0.05
) -> float:
    """
    计算期权Gamma
    
    Returns:
        Gamma值
    """
    from math import log, sqrt
    
    if time_to_expiry <= 0:
        return 0.0
    
    d1 = (log(spot_price / strike_price) + 
          (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / \
          (volatility * sqrt(time_to_expiry))
    
    gamma = stats.norm.pdf(d1) / (spot_price * volatility * sqrt(time_to_expiry))
    
    return gamma


def calculate_portfolio_greeks(
    positions: List[Dict]
) -> Dict[str, float]:
    """
    计算组合Greeks
    
    Args:
        positions: 持仓列表，每个包含 delta, gamma, qty, multiplier
    
    Returns:
        组合Greeks
    """
    total_delta = 0.0
    total_gamma = 0.0
    
    for pos in positions:
        delta = pos.get("delta", 0)
        gamma = pos.get("gamma", 0)
        qty = pos.get("qty", 0)
        multiplier = pos.get("multiplier", 100)  # 默认100股/合约
        
        total_delta += delta * qty * multiplier
        total_gamma += gamma * qty * multiplier
    
    return {
        "portfolio_delta": total_delta,
        "portfolio_gamma": total_gamma,
        "delta_dollars": total_delta,  # Delta对应的名义金额
    }


# ============================================================
# 风险报告生成
# ============================================================

def generate_risk_report(
    returns: np.ndarray,
    equity_curve: np.ndarray,
    positions: Optional[List[Dict]] = None,
    benchmark_returns: Optional[np.ndarray] = None,
    confidence: float = 0.95
) -> Dict:
    """
    生成完整的风险报告
    
    Args:
        returns: 收益率数组
        equity_curve: 权益曲线
        positions: 持仓列表 (可选)
        benchmark_returns: 基准收益率 (可选)
        confidence: VaR置信水平
    
    Returns:
        风险报告字典
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "confidence_level": confidence,
    }
    
    # VaR/CVaR
    report["var_metrics"] = calculate_var_all_methods(returns, confidence)
    
    # 回撤
    report["drawdown"] = calculate_drawdown(equity_curve)
    
    # 基本统计
    report["statistics"] = {
        "mean_return": np.mean(returns),
        "std_return": np.std(returns),
        "skewness": stats.skew(returns),
        "kurtosis": stats.kurtosis(returns),
        "min_return": np.min(returns),
        "max_return": np.max(returns),
    }
    
    # Beta (如果有基准)
    if benchmark_returns is not None:
        report["beta"] = calculate_beta(returns, benchmark_returns)
        report["correlation"] = np.corrcoef(returns, benchmark_returns)[0, 1]
    
    # 集中度 (如果有持仓)
    if positions:
        weights = np.array([p.get("weight", 0) for p in positions])
        report["concentration"] = {
            "hhi": calculate_hhi(weights),
            "classification": classify_concentration(calculate_hhi(weights)),
            "effective_n": calculate_effective_n(weights),
        }
        
        # Greeks (如果有期权)
        if any(p.get("delta") for p in positions):
            report["greeks"] = calculate_portfolio_greeks(positions)
    
    return report


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  风险指标模块测试")
    print("=" * 60)
    
    # 模拟数据
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, 252)  # 年化~12.5%, 波动率~32%
    equity_curve = 100000 * (1 + returns).cumprod()
    benchmark_returns = np.random.normal(0.0004, 0.015, 252)
    
    # VaR测试
    print("\n📋 VaR/CVaR 计算:")
    var_95 = calculate_var_historical(returns, 0.95)
    cvar_95 = calculate_cvar(returns, 0.95)
    print(f"  95% VaR (历史法): {var_95:.4%} (日损失)")
    print(f"  95% CVaR: {cvar_95:.4%} (尾部平均损失)")
    
    # 所有方法
    all_var = calculate_var_all_methods(returns, 0.95)
    print(f"  VaR (参数法): {all_var['var_parametric']:.4%}")
    print(f"  VaR (蒙特卡洛): {all_var['var_monte_carlo']:.4%}")
    
    # 回撤测试
    print("\n📋 回撤分析:")
    dd = calculate_drawdown(equity_curve)
    print(f"  最大回撤: {dd['max_drawdown_pct']:.2f}%")
    print(f"  当前回撤: {dd['current_drawdown_pct']:.2f}%")
    
    # Beta测试
    print("\n📋 Beta分析:")
    beta = calculate_beta(returns, benchmark_returns)
    print(f"  组合Beta: {beta:.2f}")
    
    # HHI测试
    print("\n📋 集中度分析:")
    weights = np.array([0.15, 0.12, 0.10, 0.08, 0.08, 0.07, 0.07, 0.06, 0.05, 0.04])
    hhi = calculate_hhi(weights)
    print(f"  HHI: {hhi:.4f}")
    print(f"  分类: {classify_concentration(hhi)}")
    print(f"  有效持仓数: {calculate_effective_n(weights):.1f}")
    
    # Delta测试
    print("\n📋 期权Delta:")
    delta = calculate_delta(100, 105, 0.25, 0.20, 0.05, "call")
    print(f"  Call Delta (spot=100, strike=105, 3个月): {delta:.2f}")
    
    # 完整报告
    print("\n📋 生成完整风险报告...")
    positions = [{"weight": w, "delta": 0} for w in weights]
    report = generate_risk_report(returns, equity_curve, positions, benchmark_returns)
    print(f"  报告生成时间: {report['generated_at']}")
    
    print("\n✅ 风险指标模块测试完成")