"""
风险管理面板 - Blueprint
==========================
提供专业的风险指标监控和管理功能

功能:
1. VaR/CVaR实时监控
2. 回撤分析
3. Beta和相关性监控
4. HHI集中度监控
5. 执行质量分析
"""

from flask import Blueprint, jsonify, render_template, request
import numpy as np
import json
import os
from datetime import datetime

bp = Blueprint("risk_management", __name__, url_prefix="/risk")


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
    """风险管理主页"""
    return render_template("risk_management.html")


@bp.route("/api/var_cvar")
def api_var_cvar():
    """
    获取VaR/CVaR风险指标
    
    Query参数:
    - confidence: 置信水平 (默认0.95)
    - method: 计算方法 (historical/parametric/monte_carlo/all)
    """
    from risk_metrics import (
        calculate_var_historical,
        calculate_var_parametric,
        calculate_var_monte_carlo,
        calculate_cvar
    )
    
    confidence = float(request.args.get("confidence", 0.95))
    method = request.args.get("method", "all")
    
    # 模拟收益率数据 (实际应从交易记录获取)
    # 这里使用模拟数据演示
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, 252)
    
    result = {"confidence": confidence}
    
    if method in ["all", "historical"]:
        result["var_historical"] = calculate_var_historical(returns, confidence)
    
    if method in ["all", "parametric"]:
        result["var_parametric"] = calculate_var_parametric(returns, confidence)
    
    if method in ["all", "monte_carlo"]:
        result["var_monte_carlo"] = calculate_var_monte_carlo(returns, confidence)
    
    if method == "all":
        result["cvar"] = calculate_cvar(returns, confidence)
    
    return jsonify(_fix(result))


@bp.route("/api/drawdown")
def api_drawdown():
    """
    获取回撤分析数据
    """
    from risk_metrics import calculate_drawdown, calculate_underwater_periods
    
    # 模拟权益曲线
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, 252)
    equity = 100000 * np.cumprod(1 + returns)
    
    drawdown = calculate_drawdown(equity)
    underwater = calculate_underwater_periods(equity)
    
    return jsonify(_fix({
        "drawdown": drawdown,
        "underwater_periods": underwater,
        "equity_curve": equity.tolist()[-30:]  # 最近30天
    }))


@bp.route("/api/concentration")
def api_concentration():
    """
    获取持仓集中度分析
    """
    from risk_metrics import calculate_hhi, classify_concentration, calculate_effective_n
    
    # 从配置读取持仓
    positions_file = "config/current_positions.json"
    if os.path.exists(positions_file):
        with open(positions_file) as f:
            positions = json.load(f)
        weights = [p.get("weight", 0) for p in positions]
    else:
        # 默认模拟数据
        weights = np.array([0.15, 0.12, 0.10, 0.08, 0.08, 0.07, 0.07, 0.06, 0.05, 0.04])
        weights = weights.tolist()
    
    hhi = calculate_hhi(np.array(weights))
    
    return jsonify(_fix({
        "hhi": hhi,
        "classification": classify_concentration(hhi),
        "effective_n": calculate_effective_n(np.array(weights)),
        "n_positions": len(weights),
        "weights": weights
    }))


@bp.route("/api/beta_analysis")
def api_beta_analysis():
    """
    获取Beta分析
    """
    from risk_metrics import calculate_beta, calculate_rolling_beta
    
    # 模拟组合和基准收益
    np.random.seed(42)
    market = np.random.normal(0.0004, 0.015, 252)
    portfolio = 0.8 * market + np.random.normal(0.0001, 0.01, 252)
    
    beta = calculate_beta(portfolio, market)
    rolling_beta = calculate_rolling_beta(portfolio, market, window=60)
    
    return jsonify(_fix({
        "current_beta": beta,
        "avg_beta": np.mean(rolling_beta),
        "rolling_beta": rolling_beta.tolist()[-30:],
        "interpretation": "偏高" if beta > 1.2 else "适中" if beta > 0.8 else "偏低"
    }))


@bp.route("/api/risk_report")
def api_risk_report():
    """
    生成完整风险报告
    """
    from risk_metrics import generate_risk_report
    
    # 模拟数据
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, 252)
    equity = 100000 * np.cumprod(1 + returns)
    benchmark = np.random.normal(0.0004, 0.015, 252)
    
    report = generate_risk_report(
        returns, equity,
        benchmark_returns=benchmark,
        confidence=0.95
    )
    
    return jsonify(_fix(report))


@bp.route("/api/calculate_var", methods=["POST"])
def api_calculate_var():
    """
    自定义VaR计算
    
    请求体:
    {
        "returns": [0.01, -0.02, 0.005, ...],
        "confidence": 0.95,
        "method": "historical"
    }
    """
    data = request.json or {}
    returns = np.array(data.get("returns", []))
    confidence = float(data.get("confidence", 0.95))
    method = data.get("method", "all")
    
    if len(returns) == 0:
        return jsonify({"status": "error", "message": "缺少收益率数据"})
    
    from risk_metrics import (
        calculate_var_historical,
        calculate_var_parametric,
        calculate_var_monte_carlo,
        calculate_cvar
    )
    
    result = {"confidence": confidence}
    
    if method in ["all", "historical"]:
        result["var_historical"] = calculate_var_historical(returns, confidence)
    
    if method in ["all", "parametric"]:
        result["var_parametric"] = calculate_var_parametric(returns, confidence)
    
    if method in ["all", "monte_carlo"]:
        result["var_monte_carlo"] = calculate_var_monte_carlo(returns, confidence)
    
    if method == "all":
        result["cvar"] = calculate_cvar(returns, confidence)
    
    return jsonify(_fix(result))


@bp.route("/api/save_risk_config", methods=["POST"])
def api_save_risk_config():
    """
    保存风险配置
    
    请求体:
    {
        "var_confidence": 0.95,
        "max_drawdown_limit": 0.15,
        "max_concentration": 0.25
    }
    """
    data = request.json or {}
    
    os.makedirs("config", exist_ok=True)
    config_file = "config/risk_config.json"
    
    with open(config_file, "w") as f:
        json.dump(data, f, indent=2)
    
    return jsonify({"status": "ok", "message": "风险配置已保存"})


@bp.route("/api/load_risk_config")
def api_load_risk_config():
    """加载风险配置"""
    config_file = "config/risk_config.json"
    if os.path.exists(config_file):
        with open(config_file) as f:
            config = json.load(f)
    else:
        config = {
            "var_confidence": 0.95,
            "max_drawdown_limit": 0.15,
            "max_concentration": 0.25
        }
    
    return jsonify(_fix(config))


@bp.route("/api/risk_alerts")
def api_risk_alerts():
    """
    获取风险告警
    """
    alerts = []
    
    # 检查VaR
    try:
        from risk_metrics import calculate_var_historical
        np.random.seed(42)
        returns = np.random.normal(0.0005, 0.02, 252)
        var = calculate_var_historical(returns, 0.95)
        
        if abs(var) > 0.03:
            alerts.append({
                "type": "var",
                "level": "warning",
                "message": f"VaR较高: {var:.2%}",
                "timestamp": datetime.now().isoformat()
            })
    except:
        pass
    
    # 检查集中度
    try:
        from risk_metrics import calculate_hhi
        weights = np.array([0.15, 0.12, 0.10, 0.08, 0.08, 0.07, 0.07, 0.06, 0.05, 0.04])
        hhi = calculate_hhi(weights)
        
        if hhi > 0.25:
            alerts.append({
                "type": "concentration",
                "level": "danger",
                "message": f"持仓过度集中: HHI={hhi:.3f}",
                "timestamp": datetime.now().isoformat()
            })
        elif hhi > 0.15:
            alerts.append({
                "type": "concentration",
                "level": "warning",
                "message": f"持仓集中度偏高: HHI={hhi:.3f}",
                "timestamp": datetime.now().isoformat()
            })
    except:
        pass
    
    return jsonify(_fix({"alerts": alerts}))


if __name__ == "__main__":
    # 测试
    with bp.test_client() as client:
        resp = client.get("/api/risk_alerts")
        print(resp.get_json())
