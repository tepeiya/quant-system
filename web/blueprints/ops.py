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

_status = {"running": False, "last": {}, "log": []}

DAEMON_PID_FILE = "config/daemon.pid"


def _check_daemon():
    """检查守护进程是否存活"""
    pid_file = DAEMON_PID_FILE
    if not os.path.exists(pid_file):
        logger.debug(f"daemon PID 文件不存在: {pid_file}")
        return False, 0
    try:
        with open(pid_file) as f:
            pid_str = f.read().strip()
        pid = int(pid_str)
        os.kill(pid, 0)
        logger.debug(f"daemon 运行中: PID={pid}")
        return True, pid
    except ValueError:
        logger.warning(f"daemon PID 文件内容异常: {pid_str}")
        return False, 0
    except ProcessLookupError:
        logger.warning(f"daemon PID {pid} 进程不存在，清理 PID 文件")
        try:
            os.remove(pid_file)
        except:
            pass
        return False, 0
    except Exception as e:
        logger.warning(f"daemon 状态检查异常: {e}")
        return False, 0


def _run_bg(target, name):
    """在后台线程运行任务"""
    t = threading.Thread(target=lambda: _wrap(target, name), daemon=True)
    _status["running"] = True
    _status["current"] = name
    t.start()


def _wrap(target, name):
    global _status
    try:
        target()
        _status["last"][name] = {"status": "ok", "time": str(datetime.now())}
    except Exception as e:
        _status["last"][name] = {"status": "error", "error": str(e)[:200], "time": str(datetime.now())}
    finally:
        _status["running"] = False
        _status["current"] = None


@bp.route("/")
def page():
    return render_template("ops.html")


@bp.route("/api/status")
def api_status():
    running, pid = _check_daemon()
    return jsonify({
        **_status,
        "daemon": {"running": running, "pid": pid},
    })


@bp.route("/api/daemon_start", methods=["POST"])
def api_daemon_start():
    running, pid = _check_daemon()
    if running:
        return ok(message=f"守护进程已在运行 (PID: {pid})")
    try:
        log_file = open("/tmp/daemon_web_start.log", "w")
        proc = subprocess.Popen(
            [sys.executable, "daemon.py"],
            stdout=log_file, stderr=subprocess.STDOUT,
            env={**os.environ}
        )
        # 等待守护进程启动（最长 30 秒，每 1 秒检查一次）
        for i in range(30):
            __import__("time").sleep(1)
            running, new_pid = _check_daemon()
            if running:
                return ok(message=f"守护进程已启动 (PID: {new_pid})")
        # 超时后检查日志，给出具体原因
        err_log = ""
        if os.path.exists("/tmp/daemon_web_start.log"):
            with open("/tmp/daemon_web_start.log") as f:
                err_log = f.read()[-1000:]
        return err(f"启动超时（30秒），日志：{err_log}")
    except Exception as e:
        return err(f"启动失败: {str(e)}")


@bp.route("/api/daemon_stop", methods=["POST"])
def api_daemon_stop():
    running, pid = _check_daemon()
    if not running:
        return ok(message="守护进程未在运行")
    try:
        os.kill(pid, 15)  # SIGTERM
        for i in range(5):
            __import__("time").sleep(1)
            running, _ = _check_daemon()
            if not running:
                if os.path.exists(DAEMON_PID_FILE):
                    os.remove(DAEMON_PID_FILE)
                return ok(message="守护进程已停止")
        os.kill(pid, 9)  # SIGKILL
        __import__("time").sleep(1)
        if os.path.exists(DAEMON_PID_FILE):
            os.remove(DAEMON_PID_FILE)
        return ok(message="守护进程已强制停止")
    except Exception as e:
        return err(f"停止失败: {str(e)}")


@bp.route("/api/refresh_now", methods=["POST"])
def api_refresh_now():
    def task():
        from data_prod import refresh_cache
        result = refresh_cache(days_back=5)
        total = sum(result.values()) if result else 0
        with open("/tmp/refresh_last.txt", "w") as f:
            f.write(f"已更新 {len(result)} 只股票，共 {total} 行新数据\n")
            for t, n in list(result.items())[:20]:
                f.write(f"  {t}: {n} 行\n")
    _run_bg(task, "refresh_now")
    return ok(message="实时刷新已开始")


@bp.route("/api/data_warmup", methods=["POST"])
def api_data_warmup():
    def task():
        from data_prod import get_tickers, load_price_cache, save_price_cache
        import yfinance as yf, time, random, gc
        tickers = get_tickers()
        cache = load_price_cache()
        missing = [t for t in tickers if t not in cache or cache[t] is None or len(cache[t]) < 200]
        for i, tkr in enumerate(missing):
            try:
                t = yf.Ticker(tkr)
                df = t.history(start="2018-01-01", end="2026-05-17", auto_adjust=True)
                if df is not None and len(df) >= 200:
                    cache[tkr] = df
            except:
                pass
            if (i+1) % 20 == 0:
                save_price_cache(cache)
                time.sleep(0.5)
        save_price_cache(cache)
    _run_bg(task, "data_warmup")
    return ok(message="数据预热已开始")


@bp.route("/api/run_backtest", methods=["POST"])
def api_run_backtest():
    def task():
        r = subprocess.run([sys.executable, "main_final.py"],
            capture_output=True, text=True, timeout=600, env={**os.environ})
        with open("/tmp/backtest_last.txt", "w") as f:
            f.write(r.stdout + "\n" + r.stderr)
    _run_bg(task, "run_backtest")
    return ok(message="回测已开始")


@bp.route("/api/run_signal", methods=["POST"])
def api_run_signal():
    def task():
        r = subprocess.run([sys.executable, "daily_signal.py"],
            capture_output=True, text=True, timeout=300, env={**os.environ})
        with open("/tmp/signal_last.txt", "w") as f:
            f.write(r.stdout + "\n" + r.stderr)
    _run_bg(task, "run_signal")
    return ok(message="信号生成已开始")


@bp.route("/api/evolve_factors", methods=["POST"])
def api_evolve_factors():
    def task():
        r = subprocess.run([sys.executable, "factor_learner.py"],
            capture_output=True, text=True, timeout=300, env={**os.environ})
        with open("/tmp/evolve_last.txt", "w") as f:
            f.write(r.stdout + "\n" + r.stderr)
    _run_bg(task, "evolve_factors")
    return ok(message="因子进化已开始")


@bp.route("/api/run_weekly", methods=["POST"])
def api_run_weekly():
    def task():
        r = subprocess.run([sys.executable, "weekly_report.py"],
            capture_output=True, text=True, timeout=300, env={**os.environ})
        with open("/tmp/weekly_last.txt", "w") as f:
            f.write(r.stdout + "\n" + r.stderr)
    _run_bg(task, "run_weekly")
    return ok(message="周报生成已开始")


@bp.route("/api/export_report", methods=["POST"])
def api_export_report():
    def task():
        r = subprocess.run([sys.executable, "backtest_report.py"],
            capture_output=True, text=True, timeout=300, env={**os.environ})
        with open("/tmp/export_last.txt", "w") as f:
            f.write(r.stdout + "\n" + r.stderr)
    _run_bg(task, "export_report")
    return ok(message="报告导出已开始")


@bp.route("/api/log/<task_name>")
def api_log(task_name):
    paths = {
        "backtest": "/tmp/backtest_last.txt", "signal": "/tmp/signal_last.txt",
        "evolve": "/tmp/evolve_last.txt", "weekly": "/tmp/weekly_last.txt",
        "export": "/tmp/export_last.txt", "refresh": "/tmp/refresh_last.txt",
        "daemon": "logs/daemon_web_start.log",
    }
    path = paths.get(task_name)
    if path and os.path.exists(path):
        with open(path) as f:
            return ok({"log": f.read()[-5000:]})
    # daemon 日志还可能写在 logs/daemon.log
    if task_name == "daemon" and os.path.exists("logs/daemon.log"):
        with open("logs/daemon.log") as f:
            return ok({"log": f.read()[-5000:]})
    return ok({"log": "(暂无日志)"})
