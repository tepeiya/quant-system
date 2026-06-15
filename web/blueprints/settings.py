"""
设置 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
import numpy as np

bp = Blueprint("settings", __name__, url_prefix="/settings")

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

@bp.route("/api/env")
def api_env():
    """环境变量状态（读+改）"""
    import os
    keys = {"ALPACA_API_KEY_ID": "Alpaca Key", "ALPACA_SECRET_KEY": "Alpaca Secret",
            "FRED_API_KEY": "FRED API Key"}
    envs = []
    for key, label in keys.items():
        val = os.environ.get(key, "")
        envs.append({"key": key, "label": label, "status": "已设置" if val else "未设置", "value": val[:8] + "****" if val else ""})
    return jsonify(_fix(envs))


@bp.route("/api/save_env", methods=["POST"])
def api_save_env():
    """保存环境变量到 .env 文件"""
    data = __import__("flask").request.json or {}
    key = data.get("key", "")
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"status": "error", "message": "参数错误"})

    import os
    env_file = ".env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            lines = f.readlines()
    else:
        lines = []

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break

    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)

    os.environ[key] = value
    return jsonify({"status": "ok", "message": f"{key} 已保存，重启后生效"})


@bp.route("/api/broker_keys")
def api_broker_keys():
    """获取券商 Key 配置（可修改）"""
    from broker_keys import get_broker_keys_status
    return jsonify(_fix(get_broker_keys_status()))


@bp.route("/api/save_broker_key", methods=["POST"])
def api_save_broker_key():
    """保存券商 Key 到配置文件"""
    from broker_keys import set_key
    data = __import__("flask").request.json or {}
    key = data.get("key", "")
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"status": "error", "message": "参数错误"})
    if value == "******":
        return jsonify({"status": "ok", "message": "未修改"})
    set_key(key, value)
    return jsonify({"status": "ok", "message": f"{key} 已保存，重启后生效"})


@bp.route("/api/brokers")
def api_brokers():
    """券商列表（可切换）"""
    from broker_manager import list_brokers, load_config, save_config
    return jsonify(_fix(list_brokers()))


@bp.route("/api/add_broker", methods=["POST"])
def api_add_broker():
    """添加自定义券商"""
    from broker_manager import load_config, save_config
    data = __import__("flask").request.json or {}
    broker_id = data.get("broker_id", "").strip()
    name = data.get("name", "").strip()
    btype = data.get("type", "alpaca")
    if not broker_id or not name:
        return jsonify({"status": "error", "message": "券商ID和名称不能为空"})
    config = load_config()
    if broker_id in config:
        return jsonify({"status": "error", "message": f"券商 {broker_id} 已存在"})
    config[broker_id] = {
        "name": name, "enabled": True, "type": btype, "paper": True,
        "env_key_id": f"CUSTOM_{broker_id.upper()}_KEY",
        "env_secret": f"CUSTOM_{broker_id.upper()}_SECRET",
    }
    save_config(config)
    return jsonify({"status": "ok", "message": f"已添加: {name}"})


@bp.route("/api/delete_broker", methods=["POST"])
def api_delete_broker():
    """删除券商"""
    from broker_manager import load_config, save_config
    data = __import__("flask").request.json or {}
    broker_id = data.get("broker_id", "").strip()
    if not broker_id:
        return jsonify({"status": "error", "message": "缺少券商ID"})
    config = load_config()
    if broker_id in config:
        del config[broker_id]
        save_config(config)
        return jsonify({"status": "ok", "message": f"已删除: {broker_id}"})
    return jsonify({"status": "error", "message": "券商不存在"})


@bp.route("/api/switch_broker", methods=["POST"])
def api_switch_broker():
    """启用/禁用或切换券商"""
    from broker_manager import BrokerManager, load_config, save_config
    data = __import__("flask").request.json or {}
    broker_id = data.get("broker_id", "")
    enabled = data.get("enabled")
    
    if enabled is not None:
        # 启用/禁用
        cfg = load_config()
        if broker_id in cfg:
            cfg[broker_id]["enabled"] = enabled
            save_config(cfg)
            return ok(message=f"{'启用' if enabled else '禁用'} {broker_id}")
        return err(f"未知券商 {broker_id}", 404)
    
    # 切换（旧逻辑）
    try:
        bm = BrokerManager()
        bm.use(broker_id)
        return ok(message=f"已切换到 {broker_id}")
    except Exception as e:
        return err(str(e))

@bp.route("/api/all_config")
def api_all_config():
    from system_config import load
    return jsonify(_fix(load()))

@bp.route("/api/save_config", methods=["POST"])
def api_save_config():
    from system_config import load, save
    data = __import__("flask").request.json or {}
    current = load()
    for k, v in data.items():
        if k in current:
            current[k] = v
    save(current)
    return jsonify({"status": "ok", "message": "配置已保存"})

@bp.route("/api/reset_config", methods=["POST"])
def api_reset_config():
    from system_config import reset
    reset()
    return jsonify({"status": "ok", "message": "配置已重置"})


# ===== 双策略资金分配 =====

@bp.route("/api/cap_allocation")
def api_cap_allocation():
    """获取当前资金分配比例"""
    import os
    return jsonify({
        "conservative": float(os.environ.get("CONSERVATIVE_CAP_RATIO", "0.5")),
        "momentum": float(os.environ.get("MOMENTUM_CAP_RATIO", "0.5")),
    })


@bp.route("/api/save_cap_allocation", methods=["POST"])
def api_save_cap_allocation():
    """保存资金分配比例到 .env 文件"""
    data = __import__("flask").request.json or {}
    conservative = float(data.get("conservative", 0.5))
    momentum = float(data.get("momentum", 0.5))
    if conservative + momentum > 1.0:
        return err("两策略合计不能超过 100%")
    if conservative < 0 or momentum < 0:
        return err("比例不能为负数")
    if conservative > 1 or momentum > 1:
        return err("比例不能超过 100%")

    import os
    env_file = ".env"
    lines = []
    if os.path.exists(env_file):
        with open(env_file) as f:
            lines = f.readlines()

    updates = {
        "CONSERVATIVE_CAP_RATIO": str(conservative),
        "MOMENTUM_CAP_RATIO": str(momentum),
    }

    for key, value in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}\n")
        os.environ[key] = value

    with open(env_file, "w") as f:
        f.writelines(lines)

    return jsonify({
        "status": "ok",
        "message": f"资金分配已保存: 保守 {conservative*100:.0f}% + 激进 {momentum*100:.0f}%",
        "data": {"conservative": conservative, "momentum": momentum},
    })

@bp.route("/")
def page():
    return render_template("settings.html")
