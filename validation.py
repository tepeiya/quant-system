"""
输入验证工具
============
统一参数验证，防止注入和格式错误
"""
import re
from typing import Any, Optional, List
from api_response import err


def validate_ticker(ticker: str) -> tuple[bool, str]:
    """验证股票代码格式"""
    if not ticker:
        return False, "股票代码不能为空"
    # 美股：1-5字母；港股：数字；A股：6位数字+后缀
    if not re.match(r'^[A-Z]{1,5}$|^[0-9]{1,5}$|^[0-9]{6}(SH|SZ)$', ticker.upper()):
        return False, f"无效的股票代码格式: {ticker}"
    return True, ticker.upper()


def validate_tickers(tickers: List[str]) -> tuple[bool, List[str]]:
    """批量验证股票代码"""
    if not tickers:
        return False, []
    valid = []
    for t in tickers:
        ok, result = validate_ticker(t)
        if ok:
            valid.append(result)
    return len(valid) == len(tickers), valid


def validate_score(score: Any) -> tuple[bool, float]:
    """验证评分（0-1范围）"""
    try:
        val = float(score)
        if val < 0 or val > 1:
            return False, 0.0
        return True, val
    except (TypeError, ValueError):
        return False, 0.0


def validate_amount(amount: Any) -> tuple[bool, float]:
    """验证金额（正数）"""
    try:
        val = float(amount)
        if val <= 0:
            return False, 0.0
        return True, val
    except (TypeError, ValueError):
        return False, 0.0


def validate_quantity(quantity: Any) -> tuple[bool, int]:
    """验证数量（正整数）"""
    try:
        val = int(quantity)
        if val <= 0:
            return False, 0
        return True, val
    except (TypeError, ValueError):
        return False, 0


def validate_strategy_name(name: str) -> tuple[bool, str]:
    """验证策略名称（字母、数字、下划线）"""
    if not name:
        return False, ""
    if not re.match(r'^[a-zA-Z0-9_]{2,32}$', name):
        return False, f"无效的策略名称: {name}"
    return True, name


def validate_broker_id(broker_id: str) -> tuple[bool, str]:
    """验证券商ID"""
    if not broker_id:
        return False, ""
    if not re.match(r'^[a-zA-Z0-9_-]{2,32}$', broker_id):
        return False, f"无效的券商ID: {broker_id}"
    return True, broker_id


def validate_namespace(namespace: str) -> tuple[bool, str]:
    """验证配置命名空间"""
    valid_namespaces = [
        "system", "intraday", "broker", "users", "factors",
        "trade_mode", "circuit", "factor_rank", "strategy_broker", "broker_keys"
    ]
    if not namespace:
        return False, ""
    if namespace not in valid_namespaces:
        return False, f"无效的命名空间: {namespace}"
    return True, namespace


def validate_json_size(data: dict, max_size: int = 10000) -> tuple[bool, str]:
    """验证JSON数据大小"""
    import json
    try:
        size = len(json.dumps(data))
        if size > max_size:
            return False, f"数据过大: {size} > {max_size}"
        return True, ""
    except Exception as e:
        return False, str(e)


def validate_required_fields(data: dict, required: List[str]) -> tuple[bool, str]:
    """验证必填字段"""
    missing = []
    for field in required:
        if field not in data or data[field] is None or data[field] == "":
            missing.append(field)
    if missing:
        return False, f"缺少必填字段: {', '.join(missing)}"
    return True, ""


def sanitize_string(s: str, max_length: int = 1000) -> str:
    """清理字符串，防止注入"""
    if not s:
        return ""
    # 截断长度
    s = s[:max_length]
    # 移除危险字符
    s = re.sub(r'[<>"\']', '', s)
    return s.strip()


def sanitize_dict(data: dict, max_value_length: int = 500) -> dict:
    """清理字典中的字符串值"""
    result = {}
    for key, value in data.items():
        key = sanitize_string(key, 50)
        if isinstance(value, str):
            result[key] = sanitize_string(value, max_value_length)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, max_value_length)
        elif isinstance(value, list):
            result[key] = [sanitize_string(v, max_value_length) if isinstance(v, str) else v for v in value[:100]]
        else:
            result[key] = value
    return result


# Flask请求验证装饰器
def validate_request(required_fields: List[str] = None, max_size: int = 5000):
    """请求验证装饰器"""
    from functools import wraps
    from flask import request

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # 验证JSON
            if request.is_json:
                data = request.json
                # 验证大小
                ok, msg = validate_json_size(data, max_size)
                if not ok:
                    return err(msg)
                # 验证必填字段
                if required_fields:
                    ok, msg = validate_required_fields(data, required_fields)
                    if not ok:
                        return err(msg)
            return f(*args, **kwargs)
        return decorated
    return decorator