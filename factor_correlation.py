"""
因子相关性检测模块
====================
检测因子间的相关性，防止因子冗余

功能:
1. 因子相关矩阵计算
2. 高相关性因子对检测
3. 因子正交化处理
4. IC衰减分析
5. 因子有效性验证
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
from scipy import stats
from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


# ============================================================
# 因子相关性分析
# ============================================================

def calculate_factor_correlation_matrix(
    factor_returns: pd.DataFrame
) -> pd.DataFrame:
    """
    计算因子收益相关性矩阵
    
    Args:
        factor_returns: DataFrame，每列是一个因子的收益序列
    
    Returns:
        相关性矩阵
    """
    return factor_returns.corr()


def detect_high_correlation_pairs(
    corr_matrix: pd.DataFrame,
    threshold: float = 0.7
) -> List[Tuple[str, str, float]]:
    """
    检测高相关性因子对
    
    Args:
        corr_matrix: 相关性矩阵
        threshold: 相关性阈值 (默认0.7)
    
    Returns:
        高相关性因子对列表 [(因子1, 因子2, 相关系数)]
    """
    high_corr_pairs = []
    
    factors = corr_matrix.columns
    n = len(factors)
    
    for i in range(n):
        for j in range(i + 1, n):
            corr_value = corr_matrix.iloc[i, j]
            if abs(corr_value) >= threshold:
                high_corr_pairs.append((factors[i], factors[j], corr_value))
    
    # 按相关性绝对值排序
    high_corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    
    return high_corr_pairs


def calculate_factor_pair_correlation(
    factor1_returns: np.ndarray,
    factor2_returns: np.ndarray
) -> float:
    """
    计算两个因子间的相关性
    
    Args:
        factor1_returns: 因子1收益序列
        factor2_returns: 因子2收益序列
    
    Returns:
        相关系数
    """
    if len(factor1_returns) != len(factor2_returns):
        min_len = min(len(factor1_returns), len(factor2_returns))
        factor1_returns = factor1_returns[:min_len]
        factor2_returns = factor2_returns[:min_len]
    
    correlation = np.corrcoef(factor1_returns, factor2_returns)[0, 1]
    return correlation


# ============================================================
# 因子正交化
# ============================================================

def orthogonalize_factors_pca(
    factor_returns: pd.DataFrame,
    n_components: Optional[int] = None
) -> pd.DataFrame:
    """
    使用PCA对因子进行正交化
    
    Args:
        factor_returns: 因子收益DataFrame
        n_components: 保留的主成分数量 (默认保留所有)
    
    Returns:
        正交化后的因子收益
    """
    if n_components is None:
        n_components = min(factor_returns.shape[1], factor_returns.shape[0])
    
    pca = PCA(n_components=n_components)
    orthogonal_factors = pca.fit_transform(factor_returns.fillna(0))
    
    # 创建新的DataFrame
    column_names = [f"PC{i+1}" for i in range(n_components)]
    orthogonal_df = pd.DataFrame(
        orthogonal_factors,
        index=factor_returns.index,
        columns=column_names
    )
    
    # 记录解释方差比例
    explained_variance = pca.explained_variance_ratio_
    logger.info(f"PCA解释方差比例: {explained_variance.sum():.2%}")
    
    return orthogonal_df, explained_variance


def orthogonalize_factors_residual(
    factor_returns: pd.DataFrame,
    target_factor: str,
    reference_factors: List[str]
) -> np.ndarray:
    """
    使用残差法对因子进行正交化
    
    将target_factor对reference_factors回归，取残差
    
    Args:
        factor_returns: 因子收益DataFrame
        target_factor: 要正交化的因子
        reference_factors: 参考因子列表
    
    Returns:
        正交化后的因子收益
    """
    y = factor_returns[target_factor].values
    X = factor_returns[reference_factors].values
    
    # 简单线性回归
    # y = X * beta + residual
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    residual = y - X @ beta
    
    return residual


# ============================================================
# IC衰减分析
# ============================================================

def calculate_factor_ic_series(
    factor_values: np.ndarray,
    future_returns: np.ndarray,
    periods: int = 12
) -> np.ndarray:
    """
    计算因子IC的时间序列衰减
    
    Args:
        factor_values: 因子值序列
        future_returns: 未来收益序列
        periods: 计算周期数
    
    Returns:
        IC序列
    """
    ic_series = []
    
    for i in range(periods):
        if i >= len(factor_values) or i >= len(future_returns):
            break
        
        # 计算IC
        ic = np.corrcoef(factor_values, future_returns)[0, 1]
        ic_series.append(ic)
    
    return np.array(ic_series)


def calculate_ic_decay_rate(ic_series: np.ndarray) -> float:
    """
    计算IC衰减率
    
    Args:
        ic_series: IC时间序列
    
    Returns:
        衰减率 (每期IC下降的百分比)
    """
    from scipy import stats as scipy_stats
    
    if len(ic_series) < 2:
        return 0.0
    
    # 使用线性回归计算衰减趋势
    x = np.arange(len(ic_series))
    y = ic_series
    
    slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(x, y)
    
    # 衰减率 = slope / initial_ic
    initial_ic = ic_series[0] if ic_series[0] != 0 else 0.01
    decay_rate = slope / abs(initial_ic)
    
    return decay_rate


def estimate_optimal_holding_period(ic_series: np.ndarray) -> int:
    """
    根据IC衰减估计最优持仓周期
    
    Args:
        ic_series: IC时间序列
    
    Returns:
        建议持仓周期 (天数)
    """
    if len(ic_series) == 0:
        return 20  # 默认20天
    
    # 找到IC降至一半的周期
    initial_ic = abs(ic_series[0])
    half_ic = initial_ic * 0.5
    
    for i, ic in enumerate(ic_series):
        if abs(ic) <= half_ic:
            return i + 1
    
    return len(ic_series)


# ============================================================
# 因子有效性检验
# ============================================================

def test_factor_significance(
    factor_returns: np.ndarray,
    confidence: float = 0.95
) -> Dict:
    """
    检验因子收益的统计显著性
    
    Args:
        factor_returns: 因子收益序列
        confidence: 置信水平
    
    Returns:
        显著性检验结果
    """
    # t检验
    from scipy import stats as scipy_stats
    t_stat, p_value = scipy_stats.ttest_1samp(factor_returns, 0)
    
    # 计算IC
    mean_return = np.mean(factor_returns)
    std_return = np.std(factor_returns)
    
    # 信息系数 (简化版)
    ic = mean_return / std_return if std_return > 0 else 0
    
    # 判断显著性
    is_significant = p_value < (1 - confidence)
    
    return {
        "t_statistic": t_stat,
        "p_value": p_value,
        "mean_return": mean_return,
        "std_return": std_return,
        "ic": ic,
        "is_significant": is_significant,
        "confidence": confidence,
    }


def calculate_factor_ir(
    factor_returns: np.ndarray
) -> float:
    """
    计算因子信息比率 (IR)
    
    IR = mean / std * sqrt(periods)
    
    Args:
        factor_returns: 因子收益序列
    
    Returns:
        信息比率
    """
    mean_ret = np.mean(factor_returns)
    std_ret = np.std(factor_returns)
    
    if std_ret == 0:
        return 0.0
    
    # 年化IR (假设日频数据)
    ir = mean_ret / std_ret * np.sqrt(252)
    
    return ir


def calculate_factor_monotonicity(
    factor_values: np.ndarray,
    returns: np.ndarray,
    n_bins: int = 5
) -> float:
    """
    计算因子单调性
    
    将股票按因子值分组，检验各组收益是否单调
    
    Args:
        factor_values: 因子值
        returns: 对应收益
        n_bins: 分组数量
    
    Returns:
        单调性得分 (-1到1)
    """
    from scipy import stats as scipy_stats
    
    # 按因子值分组
    bins = np.percentile(factor_values, np.linspace(0, 100, n_bins + 1))
    
    group_returns = []
    for i in range(n_bins):
        mask = (factor_values >= bins[i]) & (factor_values <= bins[i + 1])
        if mask.sum() > 0:
            group_returns.append(np.mean(returns[mask]))
    
    if len(group_returns) < 2:
        return 0.0
    
    # 计算单调性 (Spearman相关)
    monotonicity = scipy_stats.spearmanr(
        np.arange(len(group_returns)),
        group_returns
    ).correlation
    
    return monotonicity


# ============================================================
# 因子质量报告
# ============================================================

def generate_factor_quality_report(
    factor_returns: pd.DataFrame,
    threshold: float = 0.7
) -> Dict:
    """
    生成因子质量报告
    
    Args:
        factor_returns: 因子收益DataFrame
        threshold: 相关性阈值
    
    Returns:
        因子质量报告
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "n_factors": len(factor_returns.columns),
        "n_periods": len(factor_returns),
    }
    
    # 相关性分析
    corr_matrix = calculate_factor_correlation_matrix(factor_returns)
    high_corr_pairs = detect_high_correlation_pairs(corr_matrix, threshold)
    
    report["correlation_analysis"] = {
        "high_correlation_pairs": high_corr_pairs,
        "n_high_corr_pairs": len(high_corr_pairs),
        "max_correlation": corr_matrix.abs().max().max() if len(high_corr_pairs) > 0 else 0,
        "avg_correlation": corr_matrix.abs().mean().mean(),
    }
    
    # 各因子有效性
    factor_stats = {}
    for factor in factor_returns.columns:
        returns = factor_returns[factor].values
        stats_result = test_factor_significance(returns)
        stats_result["ir"] = calculate_factor_ir(returns)
        factor_stats[factor] = stats_result
    
    report["factor_statistics"] = factor_stats
    
    # 整体评估
    significant_factors = [
        f for f, s in factor_stats.items() 
        if s["is_significant"]
    ]
    
    report["overall_assessment"] = {
        "significant_factors": significant_factors,
        "n_significant": len(significant_factors),
        "significance_rate": len(significant_factors) / len(factor_returns.columns),
        "has_correlation_issue": len(high_corr_pairs) > 0,
    }
    
    # 添加建议 (在overall_assessment之后)
    report["overall_assessment"]["recommendation"] = generate_recommendation(report)
    
    return report


def generate_recommendation(report: Dict) -> str:
    """
    根据分析结果生成建议
    
    Args:
        report: 因子质量报告
    
    Returns:
        建议文本
    """
    recommendations = []
    
    # 相关性问题
    if report["correlation_analysis"]["n_high_corr_pairs"] > 0:
        recommendations.append(
            f"⚠️ 发现{report['correlation_analysis']['n_high_corr_pairs']}对高相关性因子，"
            "建议进行正交化处理或剔除冗余因子"
        )
    
    # 显著性问题
    sig_rate = report["overall_assessment"]["significance_rate"]
    if sig_rate < 0.5:
        recommendations.append(
            f"⚠️ 仅{sig_rate:.0%}因子具有统计显著性，建议重新评估因子有效性"
        )
    
    if len(recommendations) == 0:
        recommendations.append("✅ 因子质量良好，无明显问题")
    
    return "\n".join(recommendations)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  因子相关性检测模块测试")
    print("=" * 60)
    
    # 模拟因子数据
    np.random.seed(42)
    n_periods = 252
    
    # 创建有一定相关性的因子
    momentum = np.random.randn(n_periods) * 0.02 + 0.001
    quality = 0.3 * momentum + 0.7 * np.random.randn(n_periods) * 0.015 + 0.0005
    value = 0.2 * momentum + 0.1 * quality + 0.7 * np.random.randn(n_periods) * 0.01
    low_vol = -0.15 * momentum + 0.85 * np.random.randn(n_periods) * 0.008
    volume = 0.25 * momentum + 0.75 * np.random.randn(n_periods) * 0.012
    
    factor_returns = pd.DataFrame({
        "momentum": momentum,
        "quality": quality,
        "value": value,
        "low_vol": low_vol,
        "volume": volume,
    })
    
    # 相关性矩阵
    print("\n📋 因子相关性矩阵:")
    corr_matrix = calculate_factor_correlation_matrix(factor_returns)
    print(corr_matrix.round(3))
    
    # 高相关性因子对
    print("\n📋 高相关性因子对 (阈值=0.5):")
    high_corr = detect_high_correlation_pairs(corr_matrix, threshold=0.5)
    for pair in high_corr:
        print(f"  {pair[0]} - {pair[1]}: {pair[2]:.3f}")
    
    # 因子有效性检验
    print("\n📋 因子有效性检验:")
    for factor in factor_returns.columns:
        stats = test_factor_significance(factor_returns[factor].values)
        print(f"  {factor}: t={stats['t_statistic']:.2f}, p={stats['p_value']:.4f}, "
              f"显著={stats['is_significant']}")
    
    # IC衰减分析
    print("\n📋 IC衰减分析:")
    ic_series = np.array([0.15, 0.12, 0.08, 0.05, 0.03, 0.02])
    decay_rate = calculate_ic_decay_rate(ic_series)
    optimal_period = estimate_optimal_holding_period(ic_series)
    print(f"  IC序列: {ic_series}")
    print(f"  衰减率: {decay_rate:.2%}")
    print(f"  建议持仓周期: {optimal_period}天")
    
    # PCA正交化
    print("\n📋 PCA正交化:")
    orthogonal_df, explained_var = orthogonalize_factors_pca(factor_returns, n_components=3)
    print(f"  保留3个主成分，解释方差: {explained_var.sum():.2%}")
    print(f"  正交化后相关性矩阵:")
    print(orthogonal_df.corr().round(3))
    
    # 生成完整报告
    print("\n📋 生成因子质量报告...")
    report = generate_factor_quality_report(factor_returns, threshold=0.5)
    print(f"  报告生成时间: {report['generated_at']}")
    print(f"  显著因子数: {report['overall_assessment']['n_significant']}")
    print(f"\n  建议:\n{report['overall_assessment']['recommendation']}")
    
    print("\n✅ 因子相关性检测模块测试完成")