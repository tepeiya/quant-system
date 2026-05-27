"""
策略参数版本管理
==============
每次修改因子权重、止损参数等自动记录版本，
可回溯到任意历史配置。

文件：config/version_history.json
"""

import os
import json
import copy
from datetime import datetime

HISTORY_FILE = "config/version_history.json"
MAX_HISTORY = 100


def snapshot(current_config: dict = None, label: str = "manual"):
    """保存当前配置快照"""
    os.makedirs("config", exist_ok=True)

    # 收集当前配置
    snapshot_data = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "config": {},
    }

    # 因子权重
    weights_file = "config/factor_weights.json"
    if os.path.exists(weights_file):
        with open(weights_file) as f:
            snapshot_data["config"]["factor_weights"] = json.load(f)
    else:
        snapshot_data["config"]["factor_weights"] = {"momentum": 55, "quality": 25, "trend": 20}

    if current_config:
        snapshot_data["config"].update(current_config)

    # 加载历史
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            history = json.load(f)

    history.append(snapshot_data)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    return snapshot_data


def list_versions() -> list:
    """列出所有版本"""
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    return [
        {"time": h.get("time", "?"), "label": h.get("label", "?"),
         "weights": h.get("config", {}).get("factor_weights", {})}
        for h in history
    ]


def restore_version(index: int = -1):
    """恢复历史版本"""
    if not os.path.exists(HISTORY_FILE):
        return None
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    if index < 0:
        index += len(history)
    if index < 0 or index >= len(history):
        return None

    entry = history[index]
    weights = entry.get("config", {}).get("factor_weights")
    if weights:
        os.makedirs("config", exist_ok=True)
        with open("config/factor_weights.json", "w") as f:
            json.dump(weights, f, indent=2)
    return entry


if __name__ == "__main__":
    import sys
    if "--list" in sys.argv:
        for i, v in enumerate(list_versions()):
            print(f"[{i}] {v['time']} {v['label']} 权重={v['weights']}")
    elif "--restore" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--restore") + 1]) if "--restore" in sys.argv and len(sys.argv) > sys.argv.index("--restore") + 1 else -1
        v = restore_version(idx)
        print(f"已恢复到: {v['time']} {v['label']}" if v else "恢复失败")
    else:
        snapshot(label="命令行手动")
        print("已保存快照")
