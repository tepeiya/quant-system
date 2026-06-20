"""
统一配置中心 (Config Center)
============================
所有配置统一通过此模块读写，底层使用 config_db 的 SQLite 数据库。
JSON 配置文件作为向下兼容的同步输出。

配置命名空间：
  system       → system_config.json (策略参数)
  intraday     → intraday_config.json (日内参数)
  broker       → broker_config.json (券商)
  users        → users.json (用户)
  factors      → factor_weights.json (因子权重)
  trade_mode   → trade_mode.json (纸盘/实盘)
  circuit      → circuit_breaker.json (熔断)
  factor_rank  → factor_ranking.json (因子排名)
  strategy_broker → strategy_broker_map.json (策略->券商映射)

用法：
  from config_center import get_config, set_config
  cfg = get_config("system")
  cfg["stop_loss_pct"] = 15
  set_config("system", cfg)
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("quant.config")

# 配置命名空间 → 文件映射
CONFIG_FILES = {
    "system":        ("config/system_config.json",        "system_config"),
    "intraday":      ("config/intraday_config.json",      "intraday_config"),
    "broker":        ("config/broker_config.json",        "broker_config"),
    "users":         ("config/users.json",                "users"),
    "factors":       ("config/factor_weights.json",       "factor_weights"),
    "trade_mode":    ("config/trade_mode.json",           "trade_mode"),
    "circuit":       ("config/circuit_breaker.json",      "circuit_breaker"),
    "factor_rank":   ("config/factor_ranking.json",       "factor_ranking"),
    "strategy_broker":("config/strategy_broker_map.json",  None),
    "broker_keys":   ("config/broker_keys.json",          "broker_keys"),
}

# 默认值（模块未初始化时返回）
DEFAULTS = {
    "system": {
        "stop_loss_pct": 14, "max_positions": 10, "score_threshold": 52,
        "rsi_exit": 90, "rsi_entry": 82, "trailing_stop_activate_pct": 12,
    },
    "intraday": {
        "enabled": True, "max_positions": 5, "stop_loss_pct": 1.5,
        "take_profit_pct": 2.5, "trailing_stop_pct": 1.0,
        "trailing_stop_enabled": False, "scan_interval_minutes": 15,
    },
    "trade_mode": {"mode": "paper"},
    "factors": {"momentum": 45, "quality": 25, "trend": 15, "value": 8, "lowvol": 7},
}


# ============================================================
# 核心读写
# ============================================================

def get_config(namespace: str) -> dict:
    """
    读取配置
    优先从 config_db (SQLite) 读取，回退到 JSON 文件
    """
    info = CONFIG_FILES.get(namespace)
    if not info:
        logger.warning(f"未知配置命名空间: {namespace}")
        return {}

    json_path, db_key = info

    # 1. 尝试从数据库读取
    if db_key:
        try:
            import config_db
            data = config_db.get_config(db_key)
            if data:
                return data
        except Exception:
            pass

    # 2. 回退到 JSON 文件
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取 {json_path} 失败: {e}")

    # 3. 返回默认值
    return dict(DEFAULTS.get(namespace, {}))


def set_config(namespace: str, data: dict, sync_json: bool = True) -> dict:
    """
    写入配置
    同时写入 SQLite 和 JSON 文件（向下兼容）
    """
    info = CONFIG_FILES.get(namespace)
    if not info:
        return {"status": "error", "message": f"未知配置: {namespace}"}

    json_path, db_key = info

    # 1. 写入 SQLite
    if db_key:
        try:
            import config_db
            config_db.set_config(db_key, data)
        except Exception as e:
            logger.warning(f"写入数据库失败: {e}")

    # 2. 同步写入 JSON 文件（向下兼容）
    if sync_json:
        try:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"写入 {json_path} 失败: {e}")
            return {"status": "error", "message": str(e)}

    return {"status": "ok", "namespace": namespace, "updated_at": str(datetime.now())}


def update_config(namespace: str, updates: dict) -> dict:
    """
    增量更新配置（只修改传入的字段，其他保留）
    """
    current = get_config(namespace)
    current.update(updates)
    return set_config(namespace, current)


# ============================================================
# 便捷访问
# ============================================================

def get(key: str, default=None):
    """
    点号路径访问，如 config_center.get("system.stop_loss_pct")
    支持: system.stop_loss_pct, intraday.trailing_stop_enabled, trade_mode.mode
    """
    parts = key.split(".", 1)
    if len(parts) != 2:
        return default
    namespace, field = parts
    cfg = get_config(namespace)
    return cfg.get(field, default)


def set(key: str, value):
    """点号路径设置"""
    parts = key.split(".", 1)
    if len(parts) != 2:
        return {"status": "error", "message": "格式: namespace.field"}
    namespace, field = parts
    return update_config(namespace, {field: value})


# ============================================================
# 批量管理
# ============================================================

def list_configs() -> list[dict]:
    """列出所有配置的概览信息"""
    results = []
    for namespace, (json_path, db_key) in CONFIG_FILES.items():
        data = get_config(namespace)
        results.append({
            "namespace": namespace,
            "file": json_path,
            "fields": len(data) if data else 0,
            "size": os.path.getsize(json_path) if os.path.exists(json_path) else 0,
            "updated": datetime.fromtimestamp(os.path.getmtime(json_path)).strftime("%Y-%m-%d %H:%M") if os.path.exists(json_path) else "-",
        })
    return results


def export_all_to_json():
    """从数据库导出所有配置到 JSON 文件"""
    results = []
    for namespace in CONFIG_FILES:
        data = get_config(namespace)
        if data:
            set_config(namespace, data, sync_json=True)
            results.append(namespace)
    return results


# ============================================================
# 与其他模块集成
# ============================================================

# 快捷访问—保持与旧 system_config.py 兼容
# 原有代码 from system_config import load 继续可用
# 新代码推荐 from config_center import get_config


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("统一配置中心")
        print("用法:")
        print("  python config_center.py list           列出所有配置")
        print("  python config_center.py get <ns>        读取配置")
        print("  python config_center.py set <ns> <json> 写入配置")
        print("  python config_center.py export          导出所有配置到JSON")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        for c in list_configs():
            print(f"  {c['namespace']:15s} {c['fields']:3d} 字段  {c['file']:40s} {c['updated']}")

    elif cmd == "get":
        ns = sys.argv[2] if len(sys.argv) > 2 else ""
        data = get_config(ns)
        if data:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"无数据: {ns}")

    elif cmd == "set":
        ns = sys.argv[2] if len(sys.argv) > 2 else ""
        json_str = sys.argv[3] if len(sys.argv) > 3 else "{}"
        try:
            data = json.loads(json_str)
            r = set_config(ns, data)
            print(f"[{r['status']}] {ns} 已更新")
        except json.JSONDecodeError:
            print("JSON 格式错误")

    elif cmd == "export":
        r = export_all_to_json()
        print(f"已导出 {len(r)} 个配置: {', '.join(r)}")

    else:
        print(f"未知命令: {cmd}")
