"""
数据源管理 - Blueprint
========================
统一管理6大数据源，支持状态查看、配置、测试
"""

from flask import Blueprint, jsonify, render_template, request
import numpy as np
from datetime import datetime

bp = Blueprint("data_hub", __name__, url_prefix="/data_hub")


def _fix(obj):
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fix(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@bp.route("/")
def page():
    return render_template("data_hub.html")


@bp.route("/api/sources")
def api_sources():
    """获取所有数据源状态"""
    from data_hub import get_data_hub
    hub = get_data_hub()
    return jsonify(_fix(hub.get_available_sources()))


@bp.route("/api/info")
def api_info():
    """获取数据源完整信息"""
    from data_hub import get_data_hub
    hub = get_data_hub()
    return jsonify(_fix(hub.get_source_info()))


@bp.route("/api/config")
def api_config():
    """获取配置"""
    from data_hub import load_config
    return jsonify(_fix(load_config()))


@bp.route("/api/config/update", methods=["POST"])
def api_config_update():
    """更新配置"""
    from data_hub import save_config, load_config
    data = request.json or {}
    config = load_config()
    config.update(data)
    save_config(config)
    return jsonify({"status": "ok", "message": "配置已更新"})


@bp.route("/api/detect_market")
def api_detect_market():
    """检测证券所属市场"""
    from data_hub import detect_market, normalize_symbol
    symbol = request.args.get("symbol", "")
    if not symbol:
        return jsonify({"error": "缺少股票代码"})
    market = detect_market(symbol)
    normalized = normalize_symbol(symbol, market)
    market_names = {
        "ashare": "A股", "us": "美股", "hk": "港股",
        "crypto": "加密货币", "futures": "期货", "forex": "外汇",
    }
    return jsonify(_fix({
        "symbol": symbol,
        "normalized": normalized,
        "market": market,
        "market_name": market_names.get(market, "未知"),
    }))


@bp.route("/api/sources_for")
def api_sources_for():
    """获取某符号可用的数据源列表"""
    from data_hub import get_data_hub
    symbol = request.args.get("symbol", "")
    if not symbol:
        return jsonify({"error": "缺少股票代码"})
    hub = get_data_hub()
    sources = hub.get_sources_for_symbol(symbol)
    return jsonify(_fix({
        "symbol": symbol,
        "sources": sources,
        "count": len(sources),
    }))


@bp.route("/api/fetch")
def api_fetch():
    """获取数据（自动路由）"""
    from data_hub import get_data_hub
    symbol = request.args.get("symbol", "")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if not symbol:
        return jsonify({"error": "缺少股票代码"})

    hub = get_data_hub()
    df = hub.load_daily(symbol, start_date, end_date, use_cache=False)

    if df is None:
        return jsonify({"error": f"无法获取 {symbol} 的数据"})

    df = df.copy()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str)

    return jsonify(_fix({
        "symbol": symbol,
        "rows": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records"),
        "sources_tried": hub.get_sources_for_symbol(symbol),
    }))


@bp.route("/api/test_source")
def api_test_source():
    """测试单个数据源"""
    from data_hub import get_data_hub
    source_name = request.args.get("source", "")
    symbol = request.args.get("symbol", "AAPL")

    hub = get_data_hub()
    if source_name not in hub._loaders:
        return jsonify({"error": f"未知数据源: {source_name}"})

    loader = hub._loaders[source_name]
    if not loader.is_available():
        return jsonify({
            "source": source_name,
            "available": False,
            "message": f"{source_name} 不可用（未安装或未配置）",
        })

    try:
        df = loader.load_daily(symbol)
        if df is not None and len(df) > 0:
            return jsonify(_fix({
                "source": source_name,
                "available": True,
                "success": True,
                "rows": len(df),
                "message": f"成功获取 {len(df)} 条数据",
            }))
        else:
            return jsonify({
                "source": source_name,
                "available": True,
                "success": False,
                "message": f"数据源可用但未返回数据",
            })
    except Exception as e:
        return jsonify({
            "source": source_name,
            "available": True,
            "success": False,
            "message": str(e)[:100],
        })