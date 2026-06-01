"""
券商管理 - 独立页面 + 独立API
所有功能不依赖 settings 蓝图
"""
from flask import Blueprint, jsonify, render_template, request
from api_response import ok, err
import os, json, logging

logger = logging.getLogger("quant.brokers")
bp = Blueprint("brokers", __name__, url_prefix="/brokers")

BROKER_CONFIG = "config/broker_config.json"


def _load_cfg():
    if os.path.exists(BROKER_CONFIG):
        with open(BROKER_CONFIG) as f:
            return json.load(f)
    return {}


def _save_cfg(cfg):
    os.makedirs("config", exist_ok=True)
    with open(BROKER_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


@bp.route("/")
def page():
    return render_template("brokers.html")


@bp.route("/api/list")
def api_list():
    """返回所有券商列表"""
    cfg = _load_cfg()
    default = get_default_broker()
    result = []
    for bid, bc in cfg.items():
        key_set = True
        secret_set = True
        try:
            key_set = bool(os.environ.get(bc.get("env_key_id", "")))
            secret_set = bool(os.environ.get(bc.get("env_secret", "")))
        except:
            pass
        result.append({
            "id": bid,
            "name": bc.get("name", bid),
            "type": bc.get("type", "?"),
            "paper": bc.get("paper", False),
            "enabled": bc.get("enabled", False),
            "ready": bc.get("enabled", False) and key_set and secret_set,
            "default": bid == default,
        })
    return ok(result)


@bp.route("/api/toggle", methods=["POST"])
def api_toggle():
    """启用/禁用券商"""
    data = request.json or {}
    broker_id = data.get("broker_id", "")
    enabled = data.get("enabled", False)
    cfg = _load_cfg()
    if broker_id in cfg:
        cfg[broker_id]["enabled"] = enabled
        _save_cfg(cfg)
        return ok(message=f"{'启用' if enabled else '禁用'} {broker_id}")
    return err("券商不存在", 404)


@bp.route("/api/keys")
def api_keys():
    """返回所有券商的Key配置"""
    from broker_keys import get_broker_keys_status
    keys_status = get_broker_keys_status()
    # 标记默认券商
    default = get_default_broker()
    return ok({"keys": keys_status, "default": default})


def get_default_broker():
    """获取默认券商ID"""
    df = "config/default_broker.txt"
    if os.path.exists(df):
        with open(df) as f:
            return f.read().strip()
    return "alpaca_paper"


def set_default_broker(broker_id):
    df = "config/default_broker.txt"
    os.makedirs("config", exist_ok=True)
    with open(df, "w") as f:
        f.write(broker_id)


@bp.route("/api/set_default", methods=["POST"])
def api_set_default():
    """设置默认券商（同时取消其他券商默认）"""
    data = request.json or {}
    broker_id = data.get("broker_id", "")
    if broker_id:
        set_default_broker(broker_id)
        return ok(message="默认券商已更新")
    return err("参数错误")


@bp.route("/api/save_key", methods=["POST"])
def api_save_key():
    """保存某个Key"""
    from broker_keys import set_key
    data = request.json or {}
    key = data.get("key", "")
    value = data.get("value", "")
    if key and value:
        set_key(key, value)
        return ok(message="已保存")
    return err("参数不完整")
