"""
配置中心 - Blueprint
统一配置管理面板
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
from security import csrf_protect
import sys, os

bp = Blueprint("config_center", __name__, url_prefix="/config")


@bp.route("/")
def config_page():
    return render_template("config_center.html")


@bp.route("/api/list")
def api_list():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from config_center import list_configs
    return jsonify(list_configs())


@bp.route("/api/get/<namespace>")
def api_get(namespace):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from config_center import get_config
    data = get_config(namespace)
    return jsonify(data)


@bp.route("/api/set/<namespace>", methods=["POST"])
@csrf_protect
def api_set(namespace):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from config_center import set_config
    data = __import__("flask").request.json or {}
    result = set_config(namespace, data)
    if result["status"] == "ok":
        return ok(message=f"{namespace} 已保存")
    return err(result.get("message", "保存失败"))
