"""
监控中心 Blueprint
==================
系统监控、告警管理的Web界面
"""

from flask import Blueprint, render_template, request, jsonify, session
import json
import logging

logger = logging.getLogger("quant.web.monitor")

bp = Blueprint('monitor', __name__, url_prefix='/monitor')


@bp.route('/')
def monitor_page():
    """监控中心页面"""
    return render_template('monitor_dashboard.html')


@bp.route('/api/metrics')
def api_metrics():
    """获取所有指标"""
    from monitoring import get_metrics
    
    metrics = get_metrics().get_all_metrics()
    
    return jsonify({
        "success": True,
        "metrics": metrics,
        "count": len(metrics)
    })


@bp.route('/api/metrics/<name>')
def api_metric_detail(name):
    """获取单个指标详情"""
    from monitoring import get_metrics
    
    limit = int(request.args.get('limit', 100))
    data = get_metrics().get_metric(name, limit)
    
    latest = get_metrics().get_latest(name)
    
    return jsonify({
        "success": True,
        "metric_name": name,
        "latest_value": latest,
        "data": data
    })


@bp.route('/api/alerts')
def api_alerts():
    """获取告警列表"""
    from monitoring import get_alerts
    
    level = request.args.get('level')
    resolved = request.args.get('resolved') == 'true'
    limit = int(request.args.get('limit', 50))
    
    alerts = get_alerts().get_alerts(level=level, resolved=resolved, limit=limit)
    
    return jsonify({
        "success": True,
        "alerts": alerts,
        "count": len(alerts)
    })


@bp.route('/api/alerts/summary')
def api_alert_summary():
    """获取告警摘要"""
    from monitoring import get_alerts
    
    summary = get_alerts().get_alert_summary()
    
    return jsonify({
        "success": True,
        "summary": summary
    })


@bp.route('/api/alerts/<alert_id>/resolve', methods=['POST'])
def api_resolve_alert(alert_id):
    """解决告警"""
    from monitoring import get_alerts
    
    success = get_alerts().resolve_alert(alert_id)
    
    return jsonify({
        "success": success
    })


@bp.route('/api/alerts/<alert_id>/ack', methods=['POST'])
def api_ack_alert(alert_id):
    """确认告警"""
    from monitoring import get_alerts
    
    success = get_alerts().acknowledge_alert(alert_id)
    
    return jsonify({
        "success": success
    })


@bp.route('/api/status')
def api_system_status():
    """获取系统状态"""
    from monitoring import get_metrics
    
    metrics = get_metrics()
    
    status = {
        "system": {
            "cpu": metrics.get_latest("system.cpu_percent"),
            "memory": metrics.get_latest("system.memory_percent"),
            "disk": metrics.get_latest("system.disk_percent")
        },
        "app": {
            "response_time_ms": metrics.get_latest("app.response_time_ms"),
            "error_rate": metrics.get_latest("app.error_rate"),
            "active_users": metrics.get_latest("app.active_users")
        },
        "timestamp": __import__('datetime').datetime.now().isoformat()
    }
    
    return jsonify({
        "success": True,
        "status": status
    })
