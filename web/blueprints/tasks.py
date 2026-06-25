"""
任务管理 Blueprint
==================
提供任务队列的Web界面和API
"""

from flask import Blueprint, render_template, request, jsonify, session
import json
import logging

logger = logging.getLogger("quant.web.tasks")

tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')


@tasks_bp.route('/')
def task_list_page():
    """任务列表页面"""
    if not session.get('user_id'):
        from flask import redirect, url_for
        return redirect(url_for('auth.login_page'))
    
    return render_template('task_manager.html')


@tasks_bp.route('/api/list')
def api_task_list():
    """获取任务列表API"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import get_task_queue
    
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    
    tasks = get_task_queue().get_all_tasks(limit=limit, status=status)
    
    return jsonify({
        "success": True,
        "tasks": tasks,
        "count": len(tasks)
    })


@tasks_bp.route('/api/<task_id>')
def api_task_detail(task_id):
    """获取任务详情API"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import get_task_queue
    
    task = get_task_queue().get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    
    return jsonify({
        "success": True,
        "task": {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "name": task.name,
            "description": task.description,
            "status": task.status.value,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "retries": task.retries,
            "max_retries": task.max_retries,
            "logs": task.logs[-50:]
        }
    })


@tasks_bp.route('/api/create', methods=['POST'])
def api_create_task():
    """创建任务API"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import get_task_queue
    
    data = request.json or {}
    
    task_type = data.get('task_type')
    name = data.get('name', task_type)
    params = data.get('params', {})
    description = data.get('description', '')
    
    if not task_type:
        return jsonify({"success": False, "error": "缺少任务类型"}), 400
    
    user_id = session.get('user_id', '')
    
    task_id = get_task_queue().create_task(
        task_type=task_type,
        name=name,
        params=params,
        description=description,
        user_id=user_id
    )
    
    return jsonify({
        "success": True,
        "task_id": task_id
    })


@tasks_bp.route('/api/<task_id>/cancel', methods=['POST'])
def api_cancel_task(task_id):
    """取消任务API"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import get_task_queue
    
    success = get_task_queue().cancel_task(task_id)
    
    return jsonify({
        "success": success
    })


@tasks_bp.route('/api/<task_id>/retry', methods=['POST'])
def api_retry_task(task_id):
    """重试任务API"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import get_task_queue
    
    success = get_task_queue().retry_task(task_id)
    
    return jsonify({
        "success": success
    })


@tasks_bp.route('/api/quick/backtest', methods=['POST'])
def api_quick_backtest():
    """快速回测任务"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import create_backtest_task
    
    data = request.json or {}
    ticker = data.get('ticker', 'SPY')
    days = int(data.get('days', 252))
    
    task_id = create_backtest_task(ticker, days, session.get('user_id', ''))
    
    return jsonify({
        "success": True,
        "task_id": task_id
    })


@tasks_bp.route('/api/quick/stress_test', methods=['POST'])
def api_quick_stress_test():
    """快速压力测试任务"""
    if not session.get('user_id'):
        return jsonify({"error": "未登录"}), 401
    
    from task_queue import create_stress_test_task
    
    data = request.json or {}
    positions = data.get('positions', {"AAPL": 50000, "MSFT": 40000})
    
    task_id = create_stress_test_task(positions, session.get('user_id', ''))
    
    return jsonify({
        "success": True,
        "task_id": task_id
    })
