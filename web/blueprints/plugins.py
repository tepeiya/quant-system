"""
插件管理 - Blueprint
策略插件的Web管理面板
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
from security import csrf_protect
import json, os, sys, signal_bus

bp = Blueprint("plugins", __name__, url_prefix="/plugins")


@bp.route("/")
def plugins_page():
    return render_template("plugins.html")


@bp.route("/api/list")
def api_list():
    """列出所有已加载的插件"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from plugin_loader import get_loader
    loader = get_loader()
    plugins = loader.get_all_plugins()
    result = []
    for p in plugins:
        info = p.get_info()
        result.append(info)
    return jsonify(result)


@bp.route("/api/discover")
def api_discover():
    """扫描发现所有插件目录"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from plugin_loader import get_loader
    loader = get_loader()
    names = loader.discover()
    loaded = [p.name for p in loader.get_all_plugins()]
    return jsonify({
        "discovered": names,
        "loaded": loaded,
        "unloaded": [n for n in names if n not in loaded],
    })


@bp.route("/api/run/<plugin_name>", methods=["POST"])
@csrf_protect
def api_run(plugin_name):
    """手动执行单个插件"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from plugin_loader import get_loader
    loader = get_loader()
    plugin = loader.get_plugin(plugin_name)
    if not plugin:
        return err(f"插件 {plugin_name} 未加载")
    try:
        signals = plugin.generate_signals()
        count = len(signals) if signals else 0
        return ok(message=f"{plugin.display_name} 执行完成，{count}条信号")
    except Exception as e:
        return err(str(e))


@bp.route("/api/run_all", methods=["POST"])
@csrf_protect
def api_run_all():
    """执行所有已启用的插件"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from plugin_loader import get_loader, run_all
    results = run_all()
    total = sum(len(v) for v in results.values())
    return jsonify({"status": "ok", "results": results, "total": total})


@bp.route("/api/status")
def api_status():
    """插件系统状态"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from plugin_loader import get_loader
    loader = get_loader()
    plugins = loader.get_all_plugins()
    bus = signal_bus.get_bus_status()

    # 读取daemon进程状态
    daemon_status = "unknown"
    daemon_file = "config/daemon_status.json"
    if os.path.exists(daemon_file):
        try:
            with open(daemon_file) as f:
                ds = json.load(f)
                daemon_status = ds.get("last_cycle", "unknown")
        except:
            pass

    return jsonify({
        "plugin_count": len(plugins),
        "enabled_count": sum(1 for p in plugins if p.enabled),
        "strategies": [p.get_info() for p in plugins],
        "bus_pending": bus.get("pending", 0),
        "daemon_status": daemon_status,
    })
