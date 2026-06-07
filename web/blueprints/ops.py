"""
运维中心 - Blueprint
一键操作：数据预热、回测、信号生成、因子进化、健康检查
"""
from flask import Blueprint, jsonify, render_template
import os, sys, logging, subprocess, json, threading
from datetime import datetime
from api_response import ok, err

logger = logging.getLogger("quant.ops")
bp = Blueprint("ops", __name__, url_prefix="/ops")

# 后台任务状态
_status = {"running": False, "last": {}, "log": []}


def _run_bg(target, name):
    """在后台线程运行任务（不阻塞后续其他任务）"""
    import threading as _t
    global _status
    _status["running"] = True
    _status["current"] = name
    def wrapper():
        global _status
        try:
            target()
            _status["last"][name] = {"status": "ok", "time": str(datetime.now())}
        except Exception as e:
            _status["last"][name] = {"status": "error", "error": str(e)[:200], "time": str(datetime.now())}
        finally:
            _status["running"] = False
            _status["current"] = None
    _t.Thread(target=wrapper, daemon=True).start()


@bp.route("/")
def page():
    return render_template("ops.html")


@bp.route("/api/status")
def api_status():
    """返回状态，包含 daemon 守护进程是否在运行"""
    import os as _os
    daemon_pid_file = "config/daemon.pid"
    daemon_running = False
    daemon_pid = 0
    if _os.path.exists(daemon_pid_file):
        try:
            with open(daemon_pid_file) as _f:
                daemon_pid = int(_f.read().strip())
            # 检查进程是否存在（Docker 容器中 /proc 可能不可用，改用 kill -0）
            try:
                _os.kill(daemon_pid, 0)
                daemon_running = True
            except (OSError, ProcessLookupError):
                daemon_running = False
        except:
            pass
    return jsonify({
        **_status,
        "daemon": {
            "running": daemon_running,
            "pid": daemon_pid,
        }
    })


@bp.route("/api/data_warmup", methods=["POST"])
def api_data_warmup():
    """补全 S&P 500 全量数据缓存"""
    def task():
        from data_prod import get_tickers, load_price_cache, save_price_cache
        import yfinance as yf, time, random, gc
        tickers = get_tickers()
        cache = load_price_cache()
        missing = [t for t in tickers if t not in cache or cache[t] is None or len(cache[t]) < 200]
        cfg = {"total": len(missing), "success": 0, "fail": 0}
        for i, ticker in enumerate(missing):
            try:
                t = yf.Ticker(ticker)
                df = t.history(start="2018-01-01", end="2026-05-17", auto_adjust=True)
                if df is not None and len(df) >= 200:
                    cache[ticker] = df
                    cfg["success"] += 1
                else:
                    cfg["fail"] += 1
            except Exception:
                cfg["fail"] += 1
            if (i+1) % 20 == 0:
                save_price_cache(cache)
            if (i+1) % 5 == 0:
                time.sleep(random.uniform(0.3, 1.0))
            if (i+1) % 50 == 0:
                gc.collect()
        save_price_cache(cache)
    _run_bg(task, "data_warmup")


@bp.route("/api/daemon_start", methods=["POST"])
def api_daemon_start():
    """启动自动化交易守护进程"""
    import os as _os, subprocess, time

    pid_file = "config/daemon.pid"
    # 先检查是否已在运行
    if _os.path.exists(pid_file):
        try:
            with open(pid_file) as _f:
                old_pid = int(_f.read().strip())
            try:
                _os.kill(old_pid, 0)
                return ok(message="守护进程已在运行")
            except (OSError, ProcessLookupError):
                pass
        except:
            pass

    if _status["running"]:
        return err("有其他任务正在运行，请稍候")

    # 直接启动（不在后台线程跑）
    try:
        log_file = open("/tmp/daemon_web_start.log", "w")
        proc = subprocess.Popen(
            [sys.executable, "daemon.py", "--daemon"],
            stdout=log_file, stderr=subprocess.STDOUT,
            env={**os.environ}
        )
        time.sleep(2)
        if _os.path.exists(pid_file):
            with open(pid_file) as _f:
                new_pid = int(_f.read().strip())
            if _os.path.exists(f"/proc/{new_pid}"):
                return ok(message=f"守护进程已启动 (PID: {new_pid})")
        return ok(message="守护进程启动命令已发送，请稍后刷新查看状态")
    except Exception as e:
        return err(f"启动失败: {str(e)}")


@bp.route("/api/daemon_stop", methods=["POST"])
def api_daemon_stop():
    """停止自动化交易守护进程"""
    import os as _os, subprocess
    try:
        r = subprocess.run(
            [sys.executable, "daemon.py", "--stop"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ}
        )
        return ok(message=r.stdout.strip() or "停止命令已发送")
    except Exception as e:
        return err(f"停止失败: {str(e)}")


@bp.route("/api/refresh_now", methods=["POST"])
def api_refresh_now():
    """实时增量更新：只补最近数据，不重下全部历史"""
    def task():
        from data_prod import refresh_cache
        result = refresh_cache(days_back=5)
        total = sum(result.values()) if result else 0
        with open("/tmp/refresh_last.txt", "w") as f:
            f.write(f"已更新 {len(result)} 只股票，共 {total} 行新数据\n")
            for t, n in list(result.items())[:20]:
                f.write(f"  {t}: {n} 行\n")
            if len(result) > 20:
                f.write(f"  ... 还有 {len(result)-20} 只\n")
    _run_bg(task, "refresh_now")
    return ok(message="实时刷新已开始，只更新最近数据")
    return ok(message="数据预热已开始，请查看进度")


@bp.route("/api/run_backtest", methods=["POST"])
def api_run_backtest():
    """运行完整回测"""
    def task():
        # 在子进程中运行，避免阻塞
        result = subprocess.run(
            [sys.executable, "main_final.py"],
            capture_output=True, text=True, timeout=600,
            env={**os.environ}
        )
        with open("/tmp/backtest_last.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
    _run_bg(task, "run_backtest")
    return ok(message="回测已开始，完成后可在日志查看结果")


@bp.route("/api/run_signal", methods=["POST"])
def api_run_signal():
    """生成今日信号"""
    def task():
        result = subprocess.run(
            [sys.executable, "daily_signal.py"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ}
        )
        with open("/tmp/signal_last.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
    _run_bg(task, "run_signal")
    return ok(message="信号生成已开始")


@bp.route("/api/evolve_factors", methods=["POST"])
def api_evolve_factors():
    """因子自动进化"""
    def task():
        result = subprocess.run(
            [sys.executable, "factor_learner.py"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ}
        )
        with open("/tmp/evolve_last.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
    _run_bg(task, "evolve_factors")
    return ok(message="因子进化已开始")


@bp.route("/api/run_weekly", methods=["POST"])
def api_run_weekly():
    """生成周报"""
    def task():
        result = subprocess.run(
            [sys.executable, "weekly_report.py"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ}
        )
        with open("/tmp/weekly_last.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
    _run_bg(task, "run_weekly")
    return ok(message="周报生成已开始")


@bp.route("/api/export_report", methods=["POST"])
def api_export_report():
    """导出回测报告"""
    def task():
        result = subprocess.run(
            [sys.executable, "backtest_report.py"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ}
        )
        with open("/tmp/export_last.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
    _run_bg(task, "export_report")
    return ok(message="报告导出已开始")


@bp.route("/api/log/<task_name>")
def api_log(task_name):
    """查看最近的任务日志"""
    log_files = {
        "backtest": "/tmp/backtest_last.txt",
        "signal": "/tmp/signal_last.txt",
        "evolve": "/tmp/evolve_last.txt",
        "weekly": "/tmp/weekly_last.txt",
        "export": "/tmp/export_last.txt",
        "refresh": "/tmp/refresh_last.txt",
        "daemon": "/tmp/daemon.log",
    }
    path = log_files.get(task_name)
    if path and os.path.exists(path):
        with open(path) as f:
            content = f.read()
        return ok({"log": content[-5000:]})
    # 检查 daemon.log 特殊处理
    if task_name == "daemon":
        dp = "/tmp/daemon.log"
        if os.path.exists(dp):
            with open(dp) as f:
                content = f.read()
            return ok({"log": content[-5000:]})
    return ok({"log": "(暂无日志，任务还未运行或日志文件尚未生成)"})
