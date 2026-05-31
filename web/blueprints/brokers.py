"""
券商管理 - 独立页面
"""
from flask import Blueprint, jsonify, render_template

bp = Blueprint("brokers", __name__, url_prefix="/brokers")


@bp.route("/")
def page():
    return render_template("brokers.html")
