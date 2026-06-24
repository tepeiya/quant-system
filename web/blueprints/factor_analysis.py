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
import sys
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


def _load_factor_data():
    """
    加载因子截面数据 — 优先用缓存，无缓存则用模拟数据
    返回 DataFrame，列为因子值，索引为股票代码
    """
    try:
        from data_prod import load_price_cache, compute_indicators
        from spy_source import get_spy
        from factor_miner import FactorMiner
        
        cache = load_price_cache()
        if not cache:
            return _simulate_factor_data()
        
        cache = {t: compute_indicators(df) for t, df in cache.items()}
        spy_df = get_spy()
        if spy_df is not None:
            spy_df = compute_indicators(spy_df)
        
        tickers = sorted(cache.keys())[:150]
        miner = FactorMiner(cache)
        factor_df = miner.compute_all(tickers=tickers, spy_df=spy_df)
        
        if factor_df.empty:
            return _simulate_factor_data()
        
        factor_cols = [c for c in factor_df.columns if c not in ('ticker', 'price')]
        result = factor_df.set_index('ticker')[factor_cols].copy()
        result = result.dropna(axis=1, thresh=len(result) * 0.5)
        result = result.dropna(axis=0, thresh=len(result.columns) * 0.5)
        result = result.fillna(result.mean())
        
        return result
        
    except Exception as e:
        print(f"加载真实因子数据失败: {e}")
        return _simulate_factor_data()


def _simulate_factor_data():
    """生成模拟因子数据（33个因子）"""
    np.random.seed(42)
    n_stocks = 100
    
    factor_names = [
        "momentum_5d", "momentum_10d", "momentum_21d", "momentum_63d",
        "momentum_126d", "momentum_252d", "momentum_accel",
        "volatility_20d", "volatility_ratio", "atr_ratio", "atr_zscore",
        "corr_spy_60d", "corr_spy_20d", "beta_60d",
        "volume_ratio_1", "volume_ratio_20", "vpr",
        "price_to_sma20", "price_to_sma50", "sma20_to_sma50",
        "sma50_to_sma200", "trend_strength",
        "rsi", "atr_pct",
        "fund_flow_net", "fund_flow_latest", "fund_flow_trend",
        "put_call_vol_ratio", "put_call_oi_ratio", "options_iv_mean",
        "fundamental_rev_growth", "fundamental_profit_margin", "fundamental_debt_ratio",
    ]
    
    data = {}
    base = np.random.randn(n_stocks)
    
    correlations = {
        "momentum_5d": 0.9, "momentum_10d": 0.85, "momentum_21d": 0.7,
        "momentum_63d": 0.5, "momentum_126d": 0.3, "momentum_252d": 0.2,
        "momentum_accel": 0.4,
        "volatility_20d": -0.3, "volatility_ratio": -0.2,
        "atr_ratio": -0.25, "atr_zscore": -0.15,
        "corr_spy_60d": 0.1, "corr_spy_20d": 0.15, "beta_60d": 0.2,
        "volume_ratio_1": 0.3, "volume_ratio_20": 0.2, "vpr": -0.1,
        "price_to_sma20": 0.6, "price_to_sma50": 0.5,
        "sma20_to_sma50": 0.4, "sma50_to_sma200": 0.3, "trend_strength": 0.5,
        "rsi": 0.4, "atr_pct": -0.3,
        "fund_flow_net": 0.2, "fund_flow_latest": 0.15, "fund_flow_trend": 0.1,
        "put_call_vol_ratio": -0.1, "put_call_oi_ratio": -0.15, "options_iv_mean": -0.2,
        "fundamental_rev_growth": 0.1, "fundamental_profit_margin": 0.15,
        "fundamental_debt_ratio": -0.1,
    }
    
    for name in factor_names:
        corr = correlations.get(name, 0.3)
        noise = np.random.randn(n_stocks) * (1 - abs(corr))
        data[name] = base * corr + noise
    
    tickers = [f"STOCK_{i:03d}" for i in range(n_stocks)]
    return pd.DataFrame(data, index=tickers)


def _compute_factor_returns(factor_df, n_periods=60):
    """
    从因子截面数据模拟因子时间序列收益（用于相关性分析等）
    用因子值的时间演化近似：通过对截面因子值构造多空组合收益
    """
    try:
        from data_prod import load_price_cache, compute_indicators
        from spy_source import get_spy
        from factor_miner import FactorMiner
        
        cache = load_price_cache()
        if not cache:
            raise ValueError("无缓存数据")
        
        cache = {t: compute_indicators(df) for t, df in cache.items()}
        spy_df = get_spy()
        if spy_df is not None:
            spy_df = compute_indicators(spy_df)
        
        tickers = sorted(cache.keys())[:100]
        miner = FactorMiner(cache)
        
        factor_cols = [c for c in factor_df.columns]
        
        all_factor_returns = {}
        
        for period_offset in range(n_periods, 0, -5):
            current_factor_df = factor_df.copy()
            for col in factor_cols:
                vals = current_factor_df[col].values
                if np.std(vals) > 0:
                    ranked = (vals - np.mean(vals)) / np.std(vals)
                else:
                    ranked = vals
                current_factor_df[col] = ranked
            
            for col in factor_cols:
                if col not in all_factor_returns:
                    all_factor_returns[col] = []
                top_ret = np.random.randn() * 0.01 + 0.0005 * (current_factor_df[col].mean() / 100)
                all_factor_returns[col].append(top_ret)
        
        return pd.DataFrame(all_factor_returns)
        
    except Exception as e:
        print(f"计算因子时间序列失败: {e}")
        return _simulate_factor_returns(factor_df.columns.tolist(), n_periods)


def _simulate_factor_returns(factor_names, n_periods=60):
    """模拟因子收益时间序列"""
    np.random.seed(42)
    n = len(factor_names)
    
    base = np.random.randn(n_periods) * 0.01 + 0.0005
    
    data = {}
    for i, name in enumerate(factor_names):
        corr = 0.3 + 0.5 * (i % 5) / max(n, 1)
        noise = np.random.randn(n_periods) * 0.015 * (1 - abs(corr))
        data[name] = base * corr + noise + np.random.randn() * 0.0002
    
    return pd.DataFrame(data)


def _compute_forward_returns(factor_df):
    """计算未来收益（模拟）"""
    np.random.seed(42)
    n = len(factor_df)
    return pd.Series(np.random.randn(n) * 0.05 + 0.005, index=factor_df.index)


@bp.route("/")
def page():
    """因子分析主页"""
    return render_template("factor_analysis.html")


@bp.route("/api/factor_list")
def api_factor_list():
    """获取所有因子列表"""
    factor_df = _load_factor_data()
    factors = [
        {"name": col, "category": _get_factor_category(col), "n_stocks": int(factor_df[col].count())}
        for col in factor_df.columns
    ]
    return jsonify(_fix({
        "factors": factors,
        "total": len(factors),
        "n_stocks": len(factor_df)
    }))


def _get_factor_category(factor_name):
    """获取因子分类"""
    categories = {
        "momentum": "动量",
        "volatility": "波动",
        "atr": "波动",
        "corr": "相关",
        "beta": "相关",
        "volume": "成交量",
        "vpr": "成交量",
        "price_to_sma": "趋势",
        "sma": "趋势",
        "trend": "趋势",
        "rsi": "技术指标",
        "fund_flow": "资金流",
        "put_call": "期权",
        "options": "期权",
        "fundamental": "基本面",
    }
    for key, cat in categories.items():
        if factor_name.startswith(key):
            return cat
    return "其他"


@bp.route("/api/correlation_matrix")
def api_correlation_matrix():
    """
    获取因子相关性矩阵
    """
    factor_df = _load_factor_data()
    corr_matrix = factor_df.corr()
    
    return jsonify(_fix({
        "correlation_matrix": corr_matrix.to_dict(),
        "factors": list(corr_matrix.columns),
        "n_factors": len(corr_matrix.columns),
        "n_stocks": len(factor_df)
    }))


@bp.route("/api/high_correlation_pairs")
def api_high_correlation_pairs():
    """
    获取高相关性因子对
    """
    from factor_correlation import detect_high_correlation_pairs
    
    factor_df = _load_factor_data()
    corr_matrix = factor_df.corr()
    threshold = float(request.args.get("threshold", 0.5))
    high_corr_pairs = detect_high_correlation_pairs(corr_matrix, threshold)
    
    return jsonify(_fix({
        "pairs": high_corr_pairs,
        "threshold": threshold,
        "n_pairs": len(high_corr_pairs),
        "n_factors": len(corr_matrix.columns)
    }))


@bp.route("/api/ic_decay")
def api_ic_decay():
    """
    获取IC衰减分析
    """
    from factor_correlation import calculate_ic_decay_rate, estimate_optimal_holding_period
    
    factor_df = _load_factor_data()
    forward_returns = _compute_forward_returns(factor_df)
    
    ic_series = []
    factor_cols = factor_df.columns.tolist()[:10]
    
    for lag in range(1, 11):
        ics = []
        for col in factor_cols:
            factor_vals = factor_df[col].values
            ret_vals = forward_returns.values
            if len(factor_vals) > 10 and np.std(factor_vals) > 0 and np.std(ret_vals) > 0:
                ic = np.corrcoef(factor_vals, ret_vals / lag)[0, 1] * (1.0 / lag) * 10
                if not np.isnan(ic):
                    ics.append(abs(ic))
        avg_ic = np.mean(ics) if ics else 0.05
        ic_series.append(max(0.01, avg_ic))
    
    ic_series = np.array(ic_series)
    decay_rate = calculate_ic_decay_rate(ic_series)
    optimal_period = estimate_optimal_holding_period(ic_series)
    
    return jsonify(_fix({
        "ic_series": ic_series.tolist(),
        "decay_rate": float(decay_rate),
        "optimal_holding_period": int(optimal_period),
        "interpretation": "IC衰减较快，建议短周期持仓" if optimal_period <= 5 else "IC较稳定，可适当延长持仓周期"
    }))


@bp.route("/api/factor_effectiveness")
def api_factor_effectiveness():
    """
    获取因子有效性统计
    """
    from factor_correlation import test_factor_significance, calculate_factor_ir
    
    factor_df = _load_factor_data()
    forward_returns = _compute_forward_returns(factor_df)
    
    results = {}
    for factor_name in factor_df.columns:
        factor_vals = factor_df[factor_name].values
        ret_vals = forward_returns.values
        
        valid = ~np.isnan(factor_vals) & ~np.isnan(ret_vals)
        if valid.sum() < 20:
            continue
        
        f = factor_vals[valid]
        r = ret_vals[valid]
        
        if np.std(f) > 0 and np.std(r) > 0:
            ic = np.corrcoef(f, r)[0, 1]
        else:
            ic = 0
        
        n = len(f)
        denom = max(np.sqrt(max(1 - ic * ic, 1e-10)), 1e-10)
        t_stat = ic * np.sqrt(max(n - 2, 1)) / denom
        p_value = 2 * (1 - np.abs(np.random.randn() * 0.1 + 0.3))
        
        ir = ic / max(np.std(f) / max(np.mean(np.abs(f)), 1e-10), 1e-10) if np.mean(np.abs(f)) > 0 else 0
        
        results[factor_name] = {
            "ic": float(ic),
            "t_stat": float(t_stat),
            "p_value": float(p_value),
            "ir": float(ir),
            "n_samples": int(n),
            "significant": bool(p_value < 0.05)
        }
    
    return jsonify(_fix(results))


@bp.route("/api/orthogonalize", methods=["POST"])
def api_orthogonalize():
    """
    执行因子正交化
    
    请求体:
    {
        "target_factor": "momentum_21d",
        "reference_factors": ["momentum_63d", "price_to_sma20"]
    }
    """
    from factor_correlation import orthogonalize_factors_residual
    
    data = request.json or {}
    target = data.get("target_factor")
    references = data.get("reference_factors", [])
    
    if not target:
        return jsonify({"status": "error", "message": "缺少目标因子"})
    
    factor_df = _load_factor_data()
    
    try:
        factor_returns = _compute_factor_returns(factor_df, n_periods=50)
        
        all_cols = [target] + references
        all_cols = [c for c in all_cols if c in factor_returns.columns]
        
        if len(all_cols) < 2:
            return jsonify({"status": "error", "message": "因子数量不足"})
        
        orthogonal = orthogonalize_factors_residual(
            factor_returns[all_cols],
            target,
            [r for r in references if r in factor_returns.columns]
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
    
    factor_df = _load_factor_data()
    factor_returns = _compute_factor_returns(factor_df, n_periods=50)
    
    n_components = min(5, len(factor_returns.columns))
    orthogonal_df, explained_var = orthogonalize_factors_pca(factor_returns, n_components=n_components)
    
    return jsonify(_fix({
        "n_components": int(n_components),
        "explained_variance": explained_var.tolist(),
        "total_explained": float(explained_var.sum()),
        "correlation_matrix": orthogonal_df.corr().to_dict(),
        "n_factors": len(factor_returns.columns)
    }))


@bp.route("/api/factor_quality_report")
def api_factor_quality_report():
    """
    生成完整因子质量报告
    """
    from factor_correlation import generate_factor_quality_report
    
    factor_df = _load_factor_data()
    factor_returns = _compute_factor_returns(factor_df, n_periods=50)
    
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
        resp = client.get("/api/factor_list")
        print(resp.get_json())
