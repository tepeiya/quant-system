"""
配置中心 - Blueprint
统一配置管理面板
"""
from flask import Blueprint, jsonify, render_template, request
from api_response import ok, err
from security import csrf_protect

# 使用别名导入，避免与根目录 config_center.py 冲突
import config_center as cc

bp = Blueprint("config_center", __name__, url_prefix="/config")


@bp.route("/")
def config_page():
    return render_template("config_center.html")


@bp.route("/api/list")
def api_list():
    return jsonify(cc.list_configs())


@bp.route("/api/get/<namespace>")
def api_get(namespace):
    data = cc.get_config(namespace)
    return jsonify(data)


@bp.route("/api/set/<namespace>", methods=["POST"])
@csrf_protect
def api_set(namespace):
    data = request.json or {}
    result = cc.set_config(namespace, data)
    if result["status"] == "ok":
        return ok(message=f"{namespace} 已保存")
    return err(result.get("message", "保存失败"))
