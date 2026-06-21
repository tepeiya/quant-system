"""
数据服务看板 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
from api_response import ok, err
from security import csrf_protect
import sys, os, signal_bus, threading, json, time
from datetime import datetime

bp = Blueprint("data_service", __name__, url_prefix="/data")

# 全局进度状态
_progress = {
    "running": False,
    "type": "",       # "增量更新" / "全量预热"
    "total": 0,
    "done": 0,
    "remaining": 0,
    "log": [],
    "start_time": None,
    "end_time": None,
    "status": "idle",  # idle / running / done / error
    "error": None,
}


def _run_warmup_bg(full):
    """后台运行预热，实时更新进度"""
    global _progress
    _progress["running"] = True
    _progress["log"] = []
    _progress["start_time"] = datetime.now()
    _progress["status"] = "running"
    _progress["error"] = None

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    try:
        if full:
            # 全量：循环预热直到所有股票补完
            from warmup_data import warmup
            from data_prod import get_tickers, load_price_cache

            all_t = get_tickers()
            total_need = len(all_t)
            _progress["type"] = "全量预热"
            _progress["log"].append(f"📡 成分股共 {total_need} 只")
            _add_log(f"📥 开始全量预热 (每批80只)")

            total_fetched = 0
            batch_num = 0
            while True:
                batch_num += 1
                r = warmup(batch_size=80)
                total_fetched += r.get("fetched", 0)
                remaining = r.get("remaining", 0)
                _progress["done"] = total_fetched
                _progress["total"] = total_need
                _progress["remaining"] = remaining
                _add_log(f"  批次{batch_num}: 已取{total_fetched}只, 剩余{remaining}只")
                if remaining <= 0:
                    break
                # 每批间隔2秒，避免限流
                time.sleep(2)

            _add_log(f"✅ 全量预热完成，共获取 {total_fetched} 只")
        else:
            # 增量：只刷新最近数据
            _progress["type"] = "增量更新"
            _add_log("📥 开始增量更新...")
            from data_service import run_update
            result = run_update(full=False)
            if result:
                _add_log("✅ 增量更新完成")
            else:
                _add_log("⚠️ 增量更新返回空")

        _progress["status"] = "done"

    except Exception as e:
        _progress["status"] = "error"
        _progress["error"] = str(e)
        _add_log(f"❌ 失败: {e}")
    finally:
        _progress["end_time"] = datetime.now()
        _progress["running"] = False


def _add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    _progress["log"].append(f"[{ts}] {msg}")


@bp.route("/")
def data_page():
    return render_template("data_service.html")


@bp.route("/api/health")
def api_health():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from data_service import check_health
    return jsonify(check_health())


@bp.route("/api/update", methods=["POST"])
@csrf_protect
def api_update():
    """手动触发更新（后台运行）"""
    global _progress
    if _progress["running"]:
        return err("已有更新任务正在运行")

    data = __import__("flask").request.json or {}
    full = data.get("full", False)

    t = threading.Thread(target=_run_warmup_bg, args=(full,), daemon=True)
    t.start()

    return ok(message=f"{'全量预热' if full else '增量更新'}已开始")


@bp.route("/api/progress")
def api_progress():
    """获取更新进度"""
    global _progress
    pct = 0
    if _progress["total"] > 0 and _progress["done"] > 0:
        pct = min(int(_progress["done"] / _progress["total"] * 100), 100)

    elapsed = ""
    if _progress["start_time"]:
        secs = (datetime.now() - _progress["start_time"]).total_seconds()
        elapsed = f"{secs:.0f}s"
        if secs > 60:
            elapsed = f"{secs//60}m{secs%60}s"

    return jsonify({
        "running": _progress["running"],
        "type": _progress["type"],
        "total": _progress["total"],
        "done": _progress["done"],
        "remaining": _progress["remaining"],
        "pct": pct,
        "log": _progress["log"][-20:],  # 最近20条
        "status": _progress["status"],
        "error": _progress["error"],
        "elapsed": elapsed,
        "start_time": str(_progress["start_time"]) if _progress["start_time"] else None,
    })


@bp.route("/api/status")
def api_status():
    """数据总线最近消息"""
    msgs = signal_bus.get_recent_messages(5)
    data_updates = [m for m in msgs if m["msg_type"] == "data_update"]
    return jsonify({
        "recent_updates": data_updates[:3] if data_updates else [],
        "total_messages": signal_bus.get_pending_count(),
    })
