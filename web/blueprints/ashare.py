"""
A股数据服务 - Blueprint
===========================
提供A股数据查询API，支持tushare/东方财富/新浪财经数据源
"""

from flask import Blueprint, jsonify, render_template, request
import numpy as np
from datetime import datetime

bp = Blueprint("ashare", __name__, url_prefix="/ashare")


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
    return render_template("ashare.html")


@bp.route("/api/config")
def api_config():
    """获取A股数据源配置"""
    from ashare_data import load_config
    config = load_config()
    return jsonify(_fix(config))


@bp.route("/api/config/update", methods=["POST"])
def api_config_update():
    """更新A股数据源配置"""
    from ashare_data import save_config, load_config
    data = request.json or {}
    
    config = load_config()
    config.update(data)
    save_config(config)
    
    return jsonify({"status": "ok", "message": "配置已更新"})


@bp.route("/api/symbol/normalize")
def api_symbol_normalize():
    """标准化股票代码"""
    from ashare_data import _normalize_symbol, _detect_security_type
    symbol = request.args.get("symbol", "")
    
    if not symbol:
        return jsonify({"error": "缺少股票代码"})
    
    normalized = _normalize_symbol(symbol)
    sec_type = _detect_security_type(symbol)
    
    type_map = {
        "stock": "股票",
        "etf": "ETF",
        "index": "指数",
        "hk": "港股",
    }
    
    return jsonify(_fix({
        "original": symbol,
        "normalized": normalized,
        "type": sec_type,
        "type_name": type_map.get(sec_type, "未知"),
    }))


@bp.route("/api/daily")
def api_daily():
    """获取日线数据"""
    from ashare_data import fetch_ashare
    symbol = request.args.get("symbol", "")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    
    if not symbol:
        return jsonify({"error": "缺少股票代码"})
    
    df = fetch_ashare(symbol, start_date, end_date)
    
    if df is None:
        return jsonify({"error": f"无法获取 {symbol} 的数据"})
    
    df = df.copy()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str)
    
    return jsonify(_fix({
        "symbol": symbol,
        "normalized": _normalize_symbol(symbol),
        "rows": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records"),
    }))


@bp.route("/api/index/constituents")
def api_index_constituents():
    """获取指数成分股"""
    from ashare_data import get_csi300_constituents, get_csi500_constituents
    
    index_code = request.args.get("index", "000300.SH")
    
    if index_code == "000300.SH":
        constituents = get_csi300_constituents()
    elif index_code == "000905.SH":
        constituents = get_csi500_constituents()
    else:
        from ashare_data import get_ashare_service
        service = get_ashare_service()
        constituents = service.get_index_constituents(index_code)
    
    return jsonify(_fix({
        "index": index_code,
        "count": len(constituents),
        "constituents": constituents,
    }))


@bp.route("/api/multi_daily")
def api_multi_daily():
    """批量获取日线数据"""
    from ashare_data import get_ashare_service
    symbols = request.args.getlist("symbols")
    
    if not symbols:
        return jsonify({"error": "缺少股票代码"})
    
    service = get_ashare_service()
    results = service.get_multi_daily(symbols)
    
    return jsonify(_fix({
        "results": {sym: df.to_dict(orient="records") if df is not None else [] 
                    for sym, df in results.items()},
        "success_count": sum(1 for df in results.values() if df is not None),
    }))


@bp.route("/api/factors")
def api_factors():
    """计算A股因子"""
    from ashare_data import fetch_ashare
    from alpha_zoo import compute_factors
    
    symbol = request.args.get("symbol", "")
    factor_names = request.args.getlist("factors")
    
    if not symbol:
        return jsonify({"error": "缺少股票代码"})
    
    df = fetch_ashare(symbol)
    if df is None:
        return jsonify({"error": f"无法获取 {symbol} 的数据"})
    
    factors = compute_factors(df, factor_names)
    
    return jsonify(_fix({
        "symbol": symbol,
        "factors": factors,
        "date": str(datetime.now()),
    }))