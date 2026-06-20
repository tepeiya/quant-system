"""
策略-券商映射管理
每个策略可以绑定到不同的券商执行
"""
import json
import os

MAPPING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "strategy_broker_map.json")

# 默认映射：所有策略走默认券商
DEFAULT_MAPPING = {
    "conservative": "alpaca_paper",
    "momentum": "alpaca_paper",
    "intraday": "alpaca_paper_intraday",
}


def load_mapping() -> dict:
    """读取策略→券商映射"""
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE) as f:
            data = json.load(f)
            # 合并默认值，新策略自动补上
            for k, v in DEFAULT_MAPPING.items():
                data.setdefault(k, v)
            return data
    return dict(DEFAULT_MAPPING)


def save_mapping(mapping: dict):
    """保存策略→券商映射"""
    os.makedirs(os.path.dirname(MAPPING_FILE), exist_ok=True)
    with open(MAPPING_FILE, "w") as f:
        json.dump(mapping, f, indent=2)


def get_broker_for_strategy(strategy_name: str) -> str:
    """获取某个策略绑定的券商ID"""
    mapping = load_mapping()
    return mapping.get(strategy_name, DEFAULT_MAPPING.get(strategy_name, ""))


def set_broker_for_strategy(strategy_name: str, broker_id: str):
    """设置某个策略绑定的券商ID"""
    mapping = load_mapping()
    mapping[strategy_name] = broker_id
    save_mapping(mapping)


def list_available_brokers() -> list[dict]:
    """列出所有可用的券商（供前端选择）"""
    from broker_manager import list_brokers
    return list_brokers()


def get_mapping_with_broker_names() -> list[dict]:
    """返回带券商名称的映射列表（供前端显示）"""
    from broker_manager import load_config
    mapping = load_mapping()
    brokers = load_config()
    result = []
    for strategy, broker_id in mapping.items():
        broker_name = brokers.get(broker_id, {}).get("name", broker_id)
        result.append({
            "strategy": strategy,
            "broker_id": broker_id,
            "broker_name": broker_name,
        })
    return result
