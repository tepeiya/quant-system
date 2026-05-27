"""
券商密钥管理
==========
在 Web 面板设置券商 API Key，存到配置文件，不依赖环境变量。
"""

import os
import json
import logging

logger = logging.getLogger("quant.keys")

KEYS_FILE = "config/broker_keys.json"

# 默认券商及Key的ID（用于界面显示）
BROKER_KEY_MAP = {
    "alpaca_paper": {
        "name": "Alpaca 纸交易",
        "fields": [
            {"key": "ALPACA_API_KEY_ID", "label": "API Key ID", "secret": False},
            {"key": "ALPACA_SECRET_KEY", "label": "Secret Key", "secret": True},
        ]
    },
    "alpaca_live": {
        "name": "Alpaca 实盘",
        "fields": [
            {"key": "ALPACA_LIVE_KEY_ID", "label": "API Key ID", "secret": False},
            {"key": "ALPACA_LIVE_SECRET", "label": "Secret Key", "secret": True},
        ]
    },
}


def load_keys() -> dict:
    """加载所有券商 Key"""
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE) as f:
            return json.load(f)
    # 首次：从环境变量导入已有 Key
    keys = {}
    for broker_id, info in BROKER_KEY_MAP.items():
        for field in info["fields"]:
            env_val = os.environ.get(field["key"], "")
            if env_val:
                keys[field["key"]] = env_val
    if keys:
        save_keys(keys)
    return keys


def save_keys(keys: dict):
    """保存 Key 到文件"""
    os.makedirs("config", exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)


def get_key(key_name: str) -> str:
    """获取指定 Key（配置文件优先，环境变量备选）"""
    keys = load_keys()
    if key_name in keys:
        return keys[key_name]
    return os.environ.get(key_name, "")


def set_key(key_name: str, value: str):
    """设置 Key"""
    keys = load_keys()
    keys[key_name] = value
    save_keys(keys)


def get_broker_keys_status() -> list:
    """获取所有券商的 Key 配置状态（不暴露具体值）"""
    keys = load_keys()
    result = []
    for broker_id, info in BROKER_KEY_MAP.items():
        fields = []
        all_set = True
        for field in info["fields"]:
            val = keys.get(field["key"], "")
            if not val:
                all_set = False
            fields.append({
                "key": field["key"],
                "label": field["label"],
                "secret": field["secret"],
                "set": bool(val),
            })
        result.append({
            "id": broker_id,
            "name": info["name"],
            "all_set": all_set,
            "fields": fields,
        })
    return result


def broker_from_alpaca_key(key_id: str, secret: str, paper: bool = True):
    """用 Key 创建 Alpaca broker 实例"""
    from alpaca.trading.client import TradingClient
    return TradingClient(key_id, secret, paper=paper)
