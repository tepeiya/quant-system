"""
因子分析面板 - Blueprint
==========================
此 Blueprint 已合并到 factors.py，现在只是重定向到因子中心页面
"""

from flask import Blueprint, redirect

bp = Blueprint("factor_analysis", __name__, url_prefix="/factor_analysis")


@bp.route("/")
def page():
    """重定向到因子中心"""
    return redirect("/factors/", code=301)
