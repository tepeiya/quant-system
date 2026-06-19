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

DAEMON_PID_FILES = ["/tmp/quant_daemon.pid", "config/daemon.pid"]


def _check_daemon():
    """检查守护进程是否存活（兼容新旧 PID 文件路径）"""
    for pid_file in DAEMON_PID_FILES:
        if not os.path.exists(pid_file):
            continue
        try:
            with open(pid_file) as f:
                pid_str = f.read().strip()
            pid = int(pid_str)
            os.kill(pid, 0)
            logger.debug(f"daemon 运行中: PID={pid}")
            return True, pid
        except ValueError:
            logger.warning(f"daemon PID 文件内容异常: {pid_str}")
            continue
        except ProcessLookupError:
            logger.warning(f"daemon PID {pid} 进程不存在，清理 PID 文件")
            try:
                os.remove(pid_file)
            except:
                pass
            continue
        except Exception as e:
            logger.warning(f"daemon 状态检查异常: {e}")
            continue
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
        # 后台启动，立即返回成功（前端 5 秒后刷新状态）
        return ok(message="守护进程启动中，5秒后自动刷新状态")
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


@bp.route("/api/run_event_backtest", methods=["POST"])
def api_run_event_backtest():
    """事件驱动回测（更真实的逐日模拟）"""
    def task():
        try:
            from data_prod import load_price_cache, compute_indicators
            from spy_source import get_spy
            from event_backtest import run_event_backtest

            cache = load_price_cache()
            cache = {t: compute_indicators(df) for t, df in cache.items()}
            spy = compute_indicators(get_spy()) if get_spy() else None

            tickers = sorted(cache.keys())[:100]
            prices = {t: cache[t] for t in tickers}

            result = run_event_backtest(prices, spy,
                                        start="2022-01-01", end=None)

            # 保存结果
            import json
            from datetime import datetime
            output = {
                "time": str(datetime.now()),
                "stock_count": len(tickers),
                "total_return_pct": result["total_return"],
                "annual_return_pct": result["annual_return"],
                "max_drawdown_pct": result["max_drawdown"],
                "sharpe_ratio": result["sharpe"],
                "total_trades": len(result.get("trade_log", [])),
            }

            with open("/tmp/event_backtest_last.txt", "w") as f:
                f.write(json.dumps(output, indent=2, ensure_ascii=False))

            logger.info(f"事件回测完成: 收益{result['total_return']:+.1f}%")

        except Exception as e:
            logger.error(f"事件回测失败: {e}")
            with open("/tmp/event_backtest_last.txt", "w") as f:
                f.write(f"错误: {str(e)}")

    _run_bg(task, "event_backtest")
    return ok(message="事件驱动回测已开始")


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


@bp.route("/api/intraday_scan", methods=["POST"])
def api_intraday_scan():
    def task():
        subprocess.run([sys.executable, "intraday.py", "--scan"],
            capture_output=True, timeout=60, env={**os.environ})
        subprocess.run([sys.executable, "intraday_trader.py", "--auto"],
            capture_output=True, timeout=60, env={**os.environ})
    _run_bg(task, "intraday_scan")
    return ok(message="日内扫描已开始")


@bp.route("/api/intraday_close", methods=["POST"])
def api_intraday_close():
    def task():
        subprocess.run([sys.executable, "intraday_trader.py", "--close-all"],
            capture_output=True, timeout=30, env={**os.environ})
    _run_bg(task, "intraday_close")
    return ok(message="日内清仓指令已发送")


@bp.route("/api/risk_check", methods=["POST"])
def api_risk_check():
    """执行风控检查 — 止损+熔断+仓位"""
    def task():
        try:
            from risk_manager import RiskManager
            from system_config import load as load_cfg
            from intraday_trader import get_alpaca as get_intraday_alpaca
            from alpaca.trading.client import TradingClient
            from broker_manager import load_config, get_default_broker_id
            import json, os

            cfg = load_cfg()
            rm = RiskManager(cfg)
            report = {"time": str(datetime.now()), "stops": [], "circuits": [], "positions": []}

            # 1. 检查主账户持仓止损
            try:
                default_id = get_default_broker_id()
                broker_cfg = load_config().get(default_id, {})
                key = os.environ.get(broker_cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
                secret = os.environ.get(broker_cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
                if key and secret:
                    client = TradingClient(key, secret, paper=broker_cfg.get("paper", True))
                    positions = {}
                    for p in client.get_all_positions():
                        qty = int(float(p.qty))
                        if qty > 0:
                            positions[p.symbol] = {
                                "qty": qty,
                                "avg_entry": float(p.avg_entry_price),
                                "current_price": float(p.current_price),
                                "pnl_pct": float(p.unrealized_plpc) * 100,
                            }
                    stops = rm.check_stops(positions)
                    report["stops"] = stops
                    if stops:
                        logger.warning(f"风控: {len(stops)}笔需止损")
                    else:
                        logger.info("风控: 无止损触发")
            except Exception as e:
                logger.error(f"主账户止损检查失败: {e}")

            # 2. 熔断检查
            try:
                acct = client.get_account()
                equity = float(acct.equity)
                daily_pnl = equity - float(acct.last_equity)
                daily_pnl_pct = daily_pnl / max(float(acct.last_equity), 1) * 100
                circuits = rm.check_circuit(daily_pnl_pct, [], 0)
                report["circuits"] = circuits
                report["daily_pnl_pct"] = round(daily_pnl_pct, 2)
            except:
                pass

            # 3. 仓位统计
            try:
                positions = client.get_all_positions()
                report["position_count"] = len(positions)
                total_mv = sum(float(p.market_value) for p in positions)
                report["total_exposure"] = round(total_mv, 2)
            except:
                pass

            # 保存报告
            os.makedirs("config", exist_ok=True)
            with open("/tmp/risk_check_result.json", "w") as f:
                json.dump(report, f, indent=2)

            logger.info(f"风控检查完成: {len(report['stops'])}止损, {len(report['circuits'])}熔断")

        except Exception as e:
            logger.error(f"风控检查失败: {e}")
            with open("/tmp/risk_check_result.json", "w") as f:
                json.dump({"error": str(e)}, f)

    _run_bg(task, "risk_check")
    return ok(message="风控检查已开始")


@bp.route("/api/risk_check_log")
def api_risk_check_log():
    import json, os
    path = "/tmp/risk_check_result.json"
    if os.path.exists(path):
        with open(path) as f:
            return ok({"log": json.dumps(json.load(f), indent=2, ensure_ascii=False)})
    return ok({"log": "(尚未运行)"})


@bp.route("/api/git_pull", methods=["POST"])
def api_git_pull():
    """从 GitHub 拉取最新代码并重启 daemon"""
    def task():
        try:
            r = subprocess.run(["git", "pull", "origin", "main"],
                capture_output=True, text=True, timeout=60)
            output = r.stdout + r.stderr
            logger.info(f"Git pull: {output[-500:]}")

            # 重新加载 blueprint
            import importlib
            importlib.invalidate_caches()
            logger.info("蓝图缓存已刷新")

            # 重启 daemon（如果正在运行）
            from daemon import stop_daemon, main
            stop_daemon()

            with open("/tmp/git_pull_result.txt", "w") as f:
                f.write(output)

            logger.info("Git pull 完成，daemon 已重启")
        except Exception as e:
            logger.error(f"Git pull 失败: {e}")
            with open("/tmp/git_pull_result.txt", "w") as f:
                f.write(f"错误: {e}")

    _run_bg(task, "git_pull")
    return ok(message="正在拉取代码并重启...")


@bp.route("/api/git_pull_log")
def api_git_pull_log():
    path = "/tmp/git_pull_result.txt"
    if os.path.exists(path):
        with open(path) as f:
            return ok({"log": f.read()[-5000:]})
    return ok({"log": "(尚未执行)"})
def api_log(task_name):
    paths = {
        "backtest": "/tmp/backtest_last.txt", "signal": "/tmp/signal_last.txt",
        "evolve": "/tmp/evolve_last.txt", "weekly": "/tmp/weekly_last.txt",
        "export": "/tmp/export_last.txt", "refresh": "/tmp/refresh_last.txt",
        "daemon": "logs/daemon_web_start.log",
        "event_backtest": "/tmp/event_backtest_last.txt",
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


@bp.route("/api/backtest_result")
def api_backtest_result():
    """读取向量化回测结果"""
    import json
    path = "signals/backtest_report.json"
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        s = data.get("strategy", {})
        b = data.get("benchmark", {})
        return ok({
            "total_return_pct": s.get("total_return_pct", 0),
            "annual_return_pct": s.get("annual_return_pct", 0),
            "max_drawdown_pct": s.get("max_drawdown_pct", 0),
            "sharpe_ratio": s.get("sharpe_ratio", 0),
            "sortino_ratio": s.get("sortino_ratio", 0),
            "calmar_ratio": s.get("calmar_ratio", 0),
            "win_rate_pct": s.get("win_rate_pct", 0),
            "total_trades": s.get("total_trades", 0),
            "alpha": b.get("alpha", 0),
            "time": data.get("time", ""),
        })
    return ok({})


@bp.route("/api/event_backtest_result")
def api_event_backtest_result():
    """读取事件驱动回测结果"""
    import json
    path = "/tmp/event_backtest_last.txt"
    if os.path.exists(path):
        with open(path) as f:
            raw = f.read()
        try:
            data = json.loads(raw)
        except:
            return ok({"log": raw})
        return ok(data)
    return ok({})
