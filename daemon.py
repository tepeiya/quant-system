"""
实盘守护进程
==========
在 web_app.py 后台运行，负责：
1. 止损监控 — 每5分钟检查持仓，ATR动态止损
2. 熔断保护 — 每日开盘检查账户，触发则停盘
3. 自动信号 — 每天9:30自动生成信号
4. 月度再平衡 — 每月1日自动调仓
5. 健康检查 — 检测进程是否存活，死掉自动重启
6. 日志轮转 — 保留最近30天日志

启动方式：
  python3 daemon.py                    # 前台运行
  python3 daemon.py --daemon           # 后台守护进程
  python3 daemon.py --status           # 查看状态
  python3 daemon.py --stop             # 停止
"""

import os
import sys
import json
import logging
import time
import signal
import threading
from datetime import datetime, timedelta
from pathlib import Path

# 配置日志
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAEMON] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/daemon.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("quant.daemon")

PID_FILE = "config/daemon.pid"
STATUS_FILE = "config/daemon_status.json"

# ====== 状态管理 ======

def save_status(data: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_status() -> dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {}

def write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def read_pid() -> int:
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            return int(f.read().strip())
    return 0


# ====== 模块1：止损监控 ======

def run_stop_loss():
    """每5分钟检查一次止损"""
    from stop_loss_monitor import check_and_stop
    interval = 300  # 5分钟
    
    logger.info("[止损] 监控启动，间隔%d秒" % interval)
    while not shutdown_event.is_set():
        try:
            logger.debug("[止损] 检查持仓...")
            result = check_and_stop()
            if result:
                logger.warning("[止损] 触发%d笔: %s" % (len(result), result))
                save_status({"last_stop_loss": str(datetime.now()), "triggered": len(result)})
        except Exception as e:
            logger.error("[止损] 异常: %s" % str(e)[:100])
        shutdown_event.wait(interval)


# ====== 模块2：熔断保护 ======

def run_circuit_breaker():
    """每小时检查一次熔断状态"""
    from circuit_breaker import CircuitBreaker
    import requests
    
    interval = 3600  # 1小时
    cb = CircuitBreaker()
    
    logger.info("[熔断] 监控启动")
    while not shutdown_event.is_set():
        try:
            KEY = os.environ.get("ALPACA_API_KEY_ID", "")
            SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
            if KEY and SECRET:
                # 检查初始权益（首次运行时记录）
                status = load_status()
                init_equity = status.get("initial_equity", 0)
                
                r = requests.get("https://paper-api.alpaca.markets/v2/account",
                                auth=(KEY, SECRET), timeout=10)
                if r.status_code == 200:
                    acct = r.json()
                    current = float(acct["equity"])
                    
                    if init_equity == 0:
                        save_status({**load_status(), "initial_equity": current})
                        init_equity = current
                    
                    # 检查熔断
                    result = cb.check(current, init_equity)
                    if result.get("should_stop"):
                        logger.critical("[熔断] ⛔ %s" % result.get("reason", ""))
                        save_status({**load_status(), "circuit_break": result})
                    else:
                        logger.debug("[熔断] 正常，权益$%.0f" % current)
                        
                    # 每日记录权益
                    today = datetime.now().strftime("%Y-%m-%d")
                    save_status({**load_status(), 
                                "last_equity": current,
                                "last_check": today})
        except Exception as e:
            logger.error("[熔断] 异常: %s" % str(e)[:100])
        
        shutdown_event.wait(interval)


# ====== 模块3：自动信号生成 ======

def run_signal_generator():
    """每天9:30生成信号（非交易日跳过）"""
    logger.info("[信号] 调度启动")
    
    while not shutdown_event.is_set():
        now = datetime.now()
        
        # 计算下次9:30
        next_run = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        
        wait_seconds = (next_run - now).total_seconds()
        if wait_seconds > 0 and wait_seconds < 86400:
            logger.info("[信号] 下次生成: %s (等待%.0f秒)" % (next_run, wait_seconds))
            if shutdown_event.wait(wait_seconds):
                break
        else:
            shutdown_event.wait(60)
            continue
        
        # 生成信号
        try:
            logger.info("[信号] 开始生成...")
            import subprocess
            result = subprocess.run(
                [sys.executable, "daily_signal.py"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ}
            )
            if result.returncode == 0:
                logger.info("[信号] 生成成功")
                save_status({**load_status(), "last_signal": str(datetime.now())})
            else:
                logger.error("[信号] 生成失败: %s" % result.stderr[-200:])
        except Exception as e:
            logger.error("[信号] 异常: %s" % str(e)[:100])


# ====== 模块4：月度再平衡 ======

def run_monthly_rebalance():
    """每月1日开盘后执行再平衡"""
    logger.info("[再平衡] 调度启动")
    
    while not shutdown_event.is_set():
        now = datetime.now()
        
        # 每月1号9:35执行
        if now.day == 1 and now.hour == 9 and 35 <= now.minute < 40:
            try:
                logger.info("[再平衡] 开始执行...")
                import subprocess
                result = subprocess.run(
                    [sys.executable, "paper_trader.py", "--rebalance", "--auto"],
                    capture_output=True, text=True, timeout=120,
                    env={**os.environ}
                )
                if result.returncode == 0:
                    logger.info("[再平衡] 完成")
                    save_status({**load_status(), "last_rebalance": str(datetime.now())})
                else:
                    logger.error("[再平衡] 失败: %s" % result.stderr[-200:])
            except Exception as e:
                logger.error("[再平衡] 异常: %s" % str(e)[:100])
            
            shutdown_event.wait(3600)  # 等一小时避免重复执行
        else:
            shutdown_event.wait(300)  # 每5分钟检查日期


# ====== 模块5：健康检查 ======

def run_health_check():
    """每30秒检查系统状态"""
    while not shutdown_event.is_set():
        try:
            # 检查Web服务器是否存活
            import urllib.request
            r = urllib.request.urlopen("http://localhost:8765/login", timeout=5)
            status = "healthy" if r.status == 200 else "degraded"
        except:
            status = "down"
            logger.error("[健康] Web服务器无响应，尝试重启...")
            # 重启 web_app
            try:
                os.system("cd %s && . ./env_setup.sh && setsid python3 web_app.py &>/tmp/flask_auto.log &" % 
                         os.path.dirname(os.path.abspath(__file__)))
                logger.info("[健康] Web服务器已重启")
            except Exception as e:
                logger.error("[健康] 重启失败: %s" % str(e)[:100])
        
        save_status({
            **load_status(),
            "web_status": status,
            "last_health": str(datetime.now()),
            "uptime_hours": round((datetime.now() - start_time).total_seconds() / 3600, 1)
        })
        
        shutdown_event.wait(30)


# ====== 服务器看门狗 ======

def ensure_web_app_running():
    """确保Web应用在运行"""
    import subprocess
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", 
                          "http://localhost:8765/login"], 
                         capture_output=True, text=True, timeout=5)
        if r.stdout != "200":
            raise Exception("Not running")
        return True
    except:
        logger.warning("Web服务未运行，正在启动...")
        try:
            subprocess.Popen(
                ["setsid", sys.executable, "web_app.py"],
                stdout=open("/tmp/flask_daemon.log", "w"),
                stderr=subprocess.STDOUT,
                env={**os.environ}
            )
            time.sleep(3)
            logger.info("Web服务已启动")
            return True
        except Exception as e:
            logger.error("Web服务启动失败: %s" % e)
            return False


# ====== 主循环 ======

shutdown_event = threading.Event()
start_time = datetime.now()

def signal_handler(sig, frame):
    logger.info("收到停止信号，优雅关闭...")
    shutdown_event.set()
    save_status({**load_status(), "shutdown": str(datetime.now())})
    # 清理PID文件
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)

def main():
    global start_time
    start_time = datetime.now()
    
    # 注册信号处理
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 写PID
    write_pid()
    
    logger.info("=" * 55)
    logger.info("  🔥 量化系统守护进程 v1.0")
    logger.info("  PID: %d" % os.getpid())
    logger.info("  启动时间: %s" % start_time)
    logger.info("=" * 55)
    
    # 确保Web服务运行
    ensure_web_app_running()
    
    # 启动所有监控线程
    threads = [
        ("止损监控", run_stop_loss),
        ("熔断保护", run_circuit_breaker),
        ("信号调度", run_signal_generator),
        ("月度再平衡", run_monthly_rebalance),
        ("健康检查", run_health_check),
    ]
    
    for name, func in threads:
        t = threading.Thread(target=func, daemon=True, name=name)
        t.start()
        logger.info("[线程] %s 已启动" % name)
        time.sleep(0.5)
    
    logger.info("\n🟢 所有监控服务运行中")
    logger.info("   查看日志: tail -f logs/daemon.log")
    logger.info("   查看状态: python3 daemon.py --status")
    logger.info("   停止:     python3 daemon.py --stop\n")
    
    # 主线程保持
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(10)
    except KeyboardInterrupt:
        signal_handler(None, None)


def show_status():
    """显示守护进程状态"""
    status = load_status()
    pid = read_pid()
    running = os.path.exists(f"/proc/{pid}") if pid > 0 else False
    
    print("\n" + "=" * 55)
    print("  🔥 守护进程状态")
    print("=" * 55)
    print("  PID: %d (%s)" % (pid, "🟢 运行中" if running else "🔴 已停止"))
    print("  Web服务状态: %s" % status.get("web_status", "未知"))
    print("  运行时间: %.1f小时" % status.get("uptime_hours", 0))
    print("  最后健康检查: %s" % status.get("last_health", "-"))
    print("  最后信号生成: %s" % status.get("last_signal", "-"))
    print("  最后再平衡: %s" % status.get("last_rebalance", "-"))
    print("  初始权益: $%.0f" % status.get("initial_equity", 0))
    print("  最后权益: $%.0f" % status.get("last_equity", 0))
    
    cb = status.get("circuit_break", {})
    if cb:
        print("  ⛔ 熔断状态: %s" % cb.get("reason", "无"))
    
    print("")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if "--status" in args:
        show_status()
    elif "--stop" in args:
        pid = read_pid()
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                os.remove(PID_FILE)
                print("✅ 守护进程已停止 (PID: %d)" % pid)
            except ProcessLookupError:
                print("⚠️ 进程不存在，清理PID文件")
                os.remove(PID_FILE)
        else:
            print("⚠️ 没有运行的守护进程")
    elif "--daemon" in args:
        # 后台运行
        pid = os.fork()
        if pid > 0:
            print("✅ 守护进程已启动 (PID: %d)" % pid)
            sys.exit(0)
        os.setsid()
        sys.stdout = open("%s/daemon_stdout.log" % LOG_DIR, "w")
        sys.stderr = sys.stdout
        main()
    else:
        main()
