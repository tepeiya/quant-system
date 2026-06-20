"""
信号总线看板 - Blueprint
显示所有策略的心跳、消息队列状态、最近消息
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
import signal_bus

bp = Blueprint("signal_bus", __name__, url_prefix="/bus")


@bp.route("/")
def bus_page():
    return render_template("bus.html")


@bp.route("/api/status")
def api_bus_status():
    return jsonify(signal_bus.get_bus_status())


@bp.route("/api/messages")
def api_bus_messages():
    msgs = signal_bus.get_recent_messages(50)
    return jsonify(msgs)


@bp.route("/api/strategies")
def api_strategies():
    return jsonify(signal_bus.get_strategy_heartbeats())


@bp.route("/api/consumers")
def api_consumers():
    return jsonify(signal_bus.get_consumers())
