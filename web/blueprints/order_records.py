"""
订单记录 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok
import sys, os, order_manager as om

bp = Blueprint("order_records", __name__, url_prefix="/orders")


@bp.route("/")
def orders_page():
    return render_template("orders.html")


@bp.route("/api/list")
def api_list():
    strategy = __import__("flask").request.args.get("strategy", "")
    status = __import__("flask").request.args.get("status", "")
    limit = int(__import__("flask").request.args.get("limit", 50))
    return jsonify(om.get_orders(strategy=strategy or None, status=status or None, limit=limit))


@bp.route("/api/today")
def api_today():
    return jsonify(om.get_today_orders())


@bp.route("/api/stats")
def api_stats():
    return jsonify(om.get_stats())
