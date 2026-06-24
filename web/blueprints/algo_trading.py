"""
算法交易面板 - Blueprint
==========================
提供VWAP/TWAP/冰山订单执行功能

功能:
1. TWAP执行计划生成
2. VWAP执行计划生成
3. 冰山订单管理
4. 市场冲击估计
5. 执行质量分析
"""

from flask import Blueprint, jsonify, render_template, request
import os
import importlib.util
import numpy as np
import json
from datetime import datetime, timedelta

bp = Blueprint("algo_trading", __name__, url_prefix="/algo_trading")

_algo_module = None


def _get_algo():
    """懒加载algo_trading核心模块，避免名称冲突"""
    global _algo_module
    if _algo_module is None:
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "algo_trading.py"
        )
        spec = importlib.util.spec_from_file_location("algo_trading_core", module_path)
        _algo_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_algo_module)
    return _algo_module


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
    return obj


@bp.route("/")
def page():
    """算法交易主页"""
    return render_template("algo_trading.html")


@bp.route("/api/twap_schedule", methods=["POST"])
def api_twap_schedule():
    """
    生成TWAP执行计划
    
    请求体:
    {
        "symbol": "AAPL",
        "quantity": 10000,
        "start_time": "09:30",
        "end_time": "16:00",
        "n_slices": 10
    }
    """
    algo = _get_algo()
    
    data = request.json or {}
    symbol = data.get("symbol", "AAPL")
    quantity = int(data.get("quantity", 10000))
    start_time_str = data.get("start_time", "09:30")
    end_time_str = data.get("end_time", "16:00")
    n_slices = int(data.get("n_slices", 10))
    
    today = datetime.now().date()
    start_time = datetime.strptime(f"{today} {start_time_str}", "%Y-%m-%d %H:%M")
    end_time = datetime.strptime(f"{today} {end_time_str}", "%Y-%m-%d %H:%M")
    
    schedule = algo.calculate_twap_schedule(quantity, start_time, end_time, n_slices)
    
    np.random.seed(42)
    expected_prices = np.random.uniform(100, 105, n_slices)
    
    for i, s in enumerate(schedule):
        s["expected_price"] = float(expected_prices[i])
        s["expected_value"] = s["quantity"] * expected_prices[i]
    
    return jsonify(_fix({
        "symbol": symbol,
        "total_quantity": quantity,
        "n_slices": n_slices,
        "duration_hours": (end_time - start_time).seconds / 3600,
        "schedule": schedule,
        "avg_expected_price": np.mean(expected_prices),
        "total_expected_value": sum([s["expected_value"] for s in schedule])
    }))


@bp.route("/api/vwap_schedule", methods=["POST"])
def api_vwap_schedule():
    """
    生成VWAP执行计划
    """
    algo = _get_algo()
    
    data = request.json or {}
    symbol = data.get("symbol", "AAPL")
    quantity = int(data.get("quantity", 10000))
    use_typical = data.get("use_typical_profile", True)
    
    if use_typical:
        volume_profile = algo.get_typical_intraday_volume_profile()
    else:
        volume_profile = np.ones(7)
    
    schedule = algo.calculate_vwap_schedule(quantity, volume_profile)
    
    np.random.seed(42)
    expected_prices = np.random.uniform(100, 105, len(schedule))
    
    for i, s in enumerate(schedule):
        s["expected_price"] = float(expected_prices[i])
        s["expected_value"] = s["quantity"] * expected_prices[i]
    
    return jsonify(_fix({
        "symbol": symbol,
        "total_quantity": quantity,
        "n_slices": len(schedule),
        "volume_profile": volume_profile.tolist(),
        "schedule": schedule,
        "expected_vwap": np.average(expected_prices, weights=[s["quantity"] for s in schedule])
    }))


@bp.route("/api/iceberg_order", methods=["POST"])
def api_iceberg_order():
    """生成冰山订单"""
    algo = _get_algo()
    
    data = request.json or {}
    symbol = data.get("symbol", "AAPL")
    quantity = int(data.get("quantity", 10000))
    visible = int(data.get("visible_quantity", 1000))
    randomize = data.get("randomize", True)
    
    slices = algo.calculate_iceberg_slices(quantity, visible, randomize)
    
    return jsonify(_fix({
        "symbol": symbol,
        "total_quantity": quantity,
        "visible_quantity": visible,
        "n_slices": len(slices),
        "slices": slices,
        "hidden_percentage": (1 - visible / quantity) * 100 if quantity > 0 else 0
    }))


@bp.route("/api/market_impact", methods=["POST"])
def api_market_impact():
    """估计市场冲击"""
    algo = _get_algo()
    
    data = request.json or {}
    order_value = float(data.get("order_value", 50000))
    daily_volume = float(data.get("daily_volume", 1000000))
    volatility = float(data.get("volatility", 0.02))
    
    impact = algo.estimate_market_impact(order_value, daily_volume, volatility)
    
    return jsonify(_fix({
        "order_value": order_value,
        "daily_volume": daily_volume,
        "participation_rate": impact["participation_rate"],
        "temporary_impact": impact["temporary_impact"],
        "permanent_impact": impact["permanent_impact"],
        "total_impact": impact["total_impact"],
        "impact_pct": impact["impact_pct"],
        "estimated_cost": impact["estimated_cost"],
        "interpretation": "高冲击" if impact["impact_pct"] > 0.5 else "中等" if impact["impact_pct"] > 0.2 else "低冲击"
    }))


@bp.route("/api/execution_cost", methods=["POST"])
def api_execution_cost():
    """估计总执行成本"""
    algo = _get_algo()
    
    data = request.json or {}
    order_value = float(data.get("order_value", 50000))
    spread = float(data.get("spread", 0.001))
    commission = float(data.get("commission", 0.0005))
    
    costs = algo.estimate_execution_cost(order_value, spread, commission)
    
    return jsonify(_fix({
        "order_value": order_value,
        "spread_cost": costs["spread_cost"],
        "commission_cost": costs["commission_cost"],
        "total_cost": costs["total_cost"],
        "total_cost_pct": costs["total_cost_pct"]
    }))


@bp.route("/api/execution_quality", methods=["POST"])
def api_execution_quality():
    """计算执行质量"""
    algo = _get_algo()
    
    data = request.json or {}
    executions = data.get("executions", [])
    benchmark_price = float(data.get("benchmark_price", 100.0))
    
    if len(executions) == 0:
        return jsonify({"status": "error", "message": "缺少执行记录"})
    
    total_qty = sum([e["quantity"] for e in executions])
    avg_price = sum([e["price"] * e["quantity"] for e in executions]) / total_qty
    
    quality = algo.calculate_execution_quality(
        avg_price,
        avg_price,
        benchmark_price,
        total_qty
    )
    
    report = algo.generate_execution_report("AAPL", total_qty, executions, benchmark_price)
    
    return jsonify(_fix({
        "total_quantity": total_qty,
        "average_price": avg_price,
        "benchmark_price": benchmark_price,
        "implementation_shortfall": quality["implementation_shortfall"],
        "quality": quality,
        "report": report
    }))


@bp.route("/api/typical_volume_profile")
def api_typical_volume_profile():
    """获取典型日内成交量分布"""
    algo = _get_algo()
    profile = algo.get_typical_intraday_volume_profile()
    
    labels = [
        "09:30-10:30", "10:30-11:30", "11:30-12:30",
        "12:30-13:30", "13:30-14:30", "14:30-15:30", "15:30-16:00"
    ]
    
    return jsonify(_fix({
        "profile": profile.tolist(),
        "labels": labels,
        "total_weight": float(profile.sum())
    }))


@bp.route("/api/save_order_template", methods=["POST"])
def api_save_order_template():
    """保存订单模板"""
    data = request.json or {}
    template_name = data.get("name", "默认模板")
    
    os.makedirs("config", exist_ok=True)
    templates_file = "config/order_templates.json"
    
    templates = {}
    if os.path.exists(templates_file):
        with open(templates_file) as f:
            templates = json.load(f)
    
    templates[template_name] = data
    templates[template_name]["created_at"] = datetime.now().isoformat()
    
    with open(templates_file, "w") as f:
        json.dump(templates, f, indent=2)
    
    return jsonify({"status": "ok", "message": f"模板 '{template_name}' 已保存"})


@bp.route("/api/load_order_templates")
def api_load_order_templates():
    """加载订单模板"""
    templates_file = "config/order_templates.json"
    if os.path.exists(templates_file):
        with open(templates_file) as f:
            templates = json.load(f)
    else:
        templates = {}
    
    return jsonify(_fix(templates))


@bp.route("/api/execution_history")
def api_execution_history():
    """获取执行历史"""
    history_file = "config/execution_history.json"
    if os.path.exists(history_file):
        with open(history_file) as f:
            history = json.load(f)
    else:
        history = [
            {
                "id": "EXEC001",
                "symbol": "AAPL",
                "algorithm": "TWAP",
                "quantity": 5000,
                "avg_price": 175.50,
                "benchmark_vwap": 175.30,
                "shortfall": 0.0011,
                "execution_time": "2024-01-15 10:30:00",
                "status": "completed"
            },
            {
                "id": "EXEC002",
                "symbol": "MSFT",
                "algorithm": "VWAP",
                "quantity": 3000,
                "avg_price": 405.20,
                "benchmark_vwap": 404.80,
                "shortfall": 0.0009,
                "execution_time": "2024-01-16 14:00:00",
                "status": "completed"
            }
        ]
    
    return jsonify(_fix({"history": history}))


if __name__ == "__main__":
    with bp.test_client() as client:
        resp = client.post("/api/twap_schedule", json={
            "symbol": "AAPL",
            "quantity": 10000,
            "n_slices": 5
        })
        print(resp.get_json())
