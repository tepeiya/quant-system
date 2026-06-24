"""
因子分析面板 - Blueprint
==========================
提供因子相关性分析和质量评估

功能:
1. 因子相关矩阵可视化
2. 高相关性因子对检测
3. IC衰减分析
4. 因子有效性检验
5. PCA正交化处理
"""

from flask import Blueprint, jsonify, render_template, request
import numpy as np
import json
import os
from datetime import datetime
import pandas as pd

bp = Blueprint("factor_analysis", __name__, url_prefix="/factor_analysis")


def _fix(obj):
    """JSON序列化辅助"""
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, tuple):
        return list(obj)
    return obj


@bp.route("/")
def page():
    """因子分析主页"""
    return render_template("factor_analysis.html")


@bp.route("/api/correlation_matrix")
def api_correlation_matrix():
    """
    获取因子相关性矩阵
    """
    # 模拟因子数据
    np.random.seed(42)
    n_periods = 252
    
    factor_returns = pd.DataFrame({
        "momentum": np.random.randn(n_periods) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(n_periods) * 0.02 + 0.001 + 0.0003,
        "value": 0.2 * np.random.randn(n_periods) * 0.015 + 0.0005,
        "low_vol": -0.15 * np.random.randn(n_periods) * 0.02 + 0.0008,
        "volume": 0.25 * np.random.randn(n_periods) * 0.018 + 0.0004,
    })
    
    # 计算相关性矩阵
    corr_matrix = factor_returns.corr()
    
    return jsonify(_fix({
        "correlation_matrix": corr_matrix.to_dict(),
        "factors": list(corr_matrix.columns),
        "n_periods": n_periods
    }))


@bp.route("/api/high_correlation_pairs")
def api_high_correlation_pairs():
    """
    获取高相关性因子对
    """
    from factor_correlation import calculate_factor_correlation_matrix, detect_high_correlation_pairs
    
    # 模拟数据
    np.random.seed(42)
    n_periods = 252
    
    factor_returns = pd.DataFrame({
        "momentum": np.random.randn(n_periods) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(n_periods) * 0.02 + 0.001 + 0.0003,
        "value": 0.2 * np.random.randn(n_periods) * 0.015 + 0.0005,
        "low_vol": -0.15 * np.random.randn(n_periods) * 0.02 + 0.0008,
        "volume": 0.25 * np.random.randn(n_periods) * 0.018 + 0.0004,
    })
    
    corr_matrix = calculate_factor_correlation_matrix(factor_returns)
    threshold = float(request.args.get("threshold", 0.5))
    high_corr_pairs = detect_high_correlation_pairs(corr_matrix, threshold)
    
    return jsonify(_fix({
        "pairs": high_corr_pairs,
        "threshold": threshold,
        "n_pairs": len(high_corr_pairs)
    }))


@bp.route("/api/ic_decay")
def api_ic_decay():
    """
    获取IC衰减分析
    """
    from factor_correlation import calculate_ic_decay_rate, estimate_optimal_holding_period
    
    # 模拟IC序列
    ic_series = np.array([0.15, 0.12, 0.08, 0.05, 0.03, 0.02, 0.015, 0.01])
    
    decay_rate = calculate_ic_decay_rate(ic_series)
    optimal_period = estimate_optimal_holding_period(ic_series)
    
    return jsonify(_fix({
        "ic_series": ic_series.tolist(),
        "decay_rate": decay_rate,
        "optimal_holding_period": optimal_period,
        "interpretation": "IC在4天内衰减至一半，建议短周期持仓" if optimal_period <= 5 else "IC较稳定，可适当延长持仓周期"
    }))


@bp.route("/api/factor_effectiveness")
def api_factor_effectiveness():
    """
    获取因子有效性统计
    """
    from factor_correlation import test_factor_significance, calculate_factor_ir
    
    np.random.seed(42)
    n_periods = 252
    
    factors = {
        "momentum": np.random.randn(n_periods) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(n_periods) * 0.02 + 0.001 + 0.0003,
        "value": 0.2 * np.random.randn(n_periods) * 0.015 + 0.0005,
        "low_vol": -0.15 * np.random.randn(n_periods) * 0.02 + 0.0008,
        "volume": 0.25 * np.random.randn(n_periods) * 0.018 + 0.0004,
    }
    
    results = {}
    for factor_name, returns in factors.items():
        stats = test_factor_significance(returns)
        stats["ir"] = calculate_factor_ir(returns)
        results[factor_name] = stats
    
    return jsonify(_fix(results))


@bp.route("/api/orthogonalize", methods=["POST"])
def api_orthogonalize():
    """
    执行因子正交化
    
    请求体:
    {
        "target_factor": "momentum",
        "reference_factors": ["quality", "value"]
    }
    """
    from factor_correlation import orthogonalize_factors_residual
    
    data = request.json or {}
    target = data.get("target_factor")
    references = data.get("reference_factors", [])
    
    if not target:
        return jsonify({"status": "error", "message": "缺少目标因子"})
    
    # 模拟数据
    np.random.seed(42)
    factor_returns = pd.DataFrame({
        "momentum": np.random.randn(252) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(252) * 0.02 + 0.001,
        "value": 0.2 * np.random.randn(252) * 0.015 + 0.0005,
    })
    
    try:
        orthogonal = orthogonalize_factors_residual(
            factor_returns,
            target,
            references
        )
        
        return jsonify(_fix({
            "status": "ok",
            "target_factor": target,
            "reference_factors": references,
            "orthogonal_returns": orthogonal.tolist()[:20],
            "summary": f"已将 {target} 对 {references} 正交化处理"
        }))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@bp.route("/api/pca_orthogonalize")
def api_pca_orthogonalize():
    """
    PCA正交化分析
    """
    from factor_correlation import orthogonalize_factors_pca
    
    np.random.seed(42)
    n_periods = 252
    
    factor_returns = pd.DataFrame({
        "momentum": np.random.randn(n_periods) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(n_periods) * 0.02 + 0.001,
        "value": 0.2 * np.random.randn(n_periods) * 0.015 + 0.0005,
        "low_vol": -0.15 * np.random.randn(n_periods) * 0.02 + 0.0008,
    })
    
    orthogonal_df, explained_var = orthogonalize_factors_pca(factor_returns, n_components=3)
    
    return jsonify(_fix({
        "n_components": 3,
        "explained_variance": explained_var.tolist(),
        "total_explained": float(explained_var.sum()),
        "correlation_matrix": orthogonal_df.corr().to_dict()
    }))


@bp.route("/api/factor_quality_report")
def api_factor_quality_report():
    """
    生成完整因子质量报告
    """
    from factor_correlation import generate_factor_quality_report
    
    np.random.seed(42)
    n_periods = 252
    
    factor_returns = pd.DataFrame({
        "momentum": np.random.randn(n_periods) * 0.02 + 0.001,
        "quality": 0.3 * np.random.randn(n_periods) * 0.02 + 0.001,
        "value": 0.2 * np.random.randn(n_periods) * 0.015 + 0.0005,
        "low_vol": -0.15 * np.random.randn(n_periods) * 0.02 + 0.0008,
        "volume": 0.25 * np.random.randn(n_periods) * 0.018 + 0.0004,
    })
    
    report = generate_factor_quality_report(factor_returns, threshold=0.5)
    
    return jsonify(_fix(report))


@bp.route("/api/save_threshold", methods=["POST"])
def api_save_threshold():
    """
    保存相关性阈值配置
    """
    data = request.json or {}
    threshold = float(data.get("threshold", 0.7))
    
    os.makedirs("config", exist_ok=True)
    with open("config/factor_correlation_threshold.json", "w") as f:
        json.dump({"threshold": threshold}, f)
    
    return jsonify({"status": "ok", "message": f"阈值已保存: {threshold}"})


if __name__ == "__main__":
    with bp.test_client() as client:
        resp = client.get("/api/factor_quality_report")
        print(resp.get_json())
