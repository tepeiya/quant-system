"""
自动化交易守护进程
================
全自动无人值守模式：
1. 每天 9:00 增量更新数据（从Alpaca补最新行情）
2. 每天 9:30 生成今日选股信号
3. 每天 9:35 自动执行调仓（对比持仓 → 买卖差额）
4. 盘中每5分钟检查止损
5. 每日收盘记录PnL

启动方式：
  python3 daemon.py                    # 前台运行
  python3 daemon.py --daemon           # 后台守护进程
  python3 daemon.py --status           # 查看状态
  python3 daemon.py --stop             # 停止
"""

import os, sys, json, logging, time, signal, threading, subprocess
from datetime import datetime, timedelta

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
shutdown_event = threading.Event()
start_time = datetime.now()


# ====== 状态管理 ======

def save_status(**updates):
    data = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE) as f:
                data = json.load(f)
        except:
            pass
    data.update(updates)
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_status() -> dict:
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def write_pid():
    import traceback
    try:
        os.makedirs(os.path.dirname(PID_FILE) or ".", exist_ok=True)
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"PID 文件已写入: {PID_FILE} -> {os.getpid()}")
    except Exception as e:
        logger.error(f"PID 文件写入失败 {PID_FILE}: {e}")
        logger.error(traceback.format_exc())


def read_pid() -> int:
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                return int(f.read().strip())
        except:
            pass
    return 0


# ====== 每日交易循环 ======

def run_daily_cycle():
    """
    核心循环：每天依次执行 数据更新 → 信号生成 → 调仓
    """
    logger.info("[主循环] 启动，每天9:00-9:35执行交易流程")

    while not shutdown_event.is_set():
        now = datetime.now()
        
        # 美股交易日检查：周末跳过
        if now.weekday() >= 5:
            next_monday = now + timedelta(days=(7 - now.weekday()))
            next_run = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
            wait = (next_run - now).total_seconds()
            logger.info(f"[主循环] 周末跳过，下次运行: {next_run}")
            shutdown_event.wait(min(wait, 3600))
            continue

        # 计算下次 9:00
        next_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_9am:
            next_9am += timedelta(days=1)
        
        wait_seconds = (next_9am - now).total_seconds()
        if wait_seconds > 0 and wait_seconds < 86400:
            logger.info(f"[主循环] 下次交易流程: {next_9am} (等待{wait_seconds/60:.0f}分钟)")
            if shutdown_event.wait(wait_seconds):
                break
        
        # ====== 交易日执行 ======
        logger.info("=" * 55)
        logger.info("  🔥 开始日交易流程")
        logger.info("=" * 55)

        today_str = now.strftime("%Y-%m-%d")
        save_status(last_cycle=today_str)

        # ---- 第一步：数据增量更新 ----
        logger.info("[步骤1/3] 增量更新数据...")
        try:
            r = subprocess.run(
                [sys.executable, "data_update.py"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  {line.strip()}")
            if r.returncode != 0:
                logger.error(f"  数据更新失败: {r.stderr[-200:]}")
            else:
                save_status(last_data_update=str(datetime.now()))
        except Exception as e:
            logger.error(f"  数据更新异常: {e}")

        # 等信号生成时间（9:30）
        now2 = datetime.now()
        target_signal = now2.replace(hour=9, minute=30, second=0, microsecond=0)
        if now2 < target_signal:
            wait_sig = (target_signal - now2).total_seconds()
            logger.info(f"  等待信号时间: {wait_sig/60:.0f}分钟")
            if shutdown_event.wait(wait_sig):
                break

        # ---- 第二步：生成信号 ----
        logger.info("[步骤2/3] 生成今日信号...")
        try:
            r = subprocess.run(
                [sys.executable, "daily_signal.py"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  {line.strip()}")
            if r.returncode != 0:
                logger.error(f"  信号生成失败: {r.stderr[-200:]}")
                # 失败后跳过调仓，等明天
                shutdown_event.wait(60)
                continue
            else:
                save_status(last_signal=str(datetime.now()))
        except Exception as e:
            logger.error(f"  信号生成异常: {e}")
            shutdown_event.wait(60)
            continue

        # 等调仓时间（9:35）
        now3 = datetime.now()
        target_rebal = now3.replace(hour=9, minute=35, second=0, microsecond=0)
        if now3 < target_rebal:
            wait_re = (target_rebal - now3).total_seconds()
            logger.info(f"  等待调仓时间: {wait_re/60:.0f}分钟")
            if shutdown_event.wait(wait_re):
                break

        # ---- 第三步：自动调仓 ----
        logger.info("[步骤3/3] 自动调仓...")
        try:
            r = subprocess.run(
                [sys.executable, "paper_trader.py", "--auto"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  {line.strip()}")
            if r.returncode != 0:
                logger.error(f"  调仓失败: {r.stderr[-200:]}")
            else:
                save_status(last_rebalance=str(datetime.now()))
        except Exception as e:
            logger.error(f"  调仓异常: {e}")

        # ---- 收盘记录权益 ----
        logger.info("[收盘] 记录今日权益...")
        try:
            r = subprocess.run(
                [sys.executable, "-c", """
from portfolio_tracker import sync_from_alpaca
pf = sync_from_alpaca()
if pf:
    import json
    print(json.dumps({"equity": pf.get("equity"), "cash": pf.get("cash"), "positions": pf.get("position_count")}))
"""],
                capture_output=True, text=True, timeout=30,
                env={**os.environ}
            )
            if r.returncode == 0 and r.stdout.strip():
                daily = json.loads(r.stdout.strip())
                save_status(
                    last_equity=daily.get("equity"),
                    last_cash=daily.get("cash"),
                    last_position_count=daily.get("positions"),
                    last_pnl_record=str(datetime.now()),
                )
                logger.info(f"  权益: ${daily.get('equity',0):.2f}, 现金: ${daily.get('cash',0):.2f}, 持仓: {daily.get('positions',0)}只")
        except Exception as e:
            logger.error(f"  收盘记录失败: {e}")

        logger.info(f"✅ 今日交易流程完成，等待明天")


# ====== 盘中止损监控 ======

def run_stop_loss_monitor():
    """每5分钟检查止损"""
    interval = 300
    logger.info("[止损] 盘中监控启动")

    while not shutdown_event.is_set():
        now = datetime.now()
        # 非交易时间不检查（美东 9:30-16:00 = 北京时间 21:30-4:00）
        # 简化：只在北京时间 6:00-10:00 之间检查（美东下午到收盘）
        # 这里不做严格判断，一直开着也行，就是止损逻辑需要实盘数据
        try:
            from stop_loss_monitor import check_and_stop
            result = check_and_stop()
            if result:
                logger.warning(f"[止损] 触发{len(result)}笔: {result}")
                save_status(last_stop_loss=str(datetime.now()), stop_triggered=len(result))
        except Exception as e:
            logger.debug(f"[止损] 检查跳过: {e}")
        shutdown_event.wait(interval)


# ====== 信号处理 ======

def signal_handler(sig, frame):
    logger.info("收到停止信号，优雅关闭...")
    shutdown_event.set()
    save_status(shutdown=str(datetime.now()))
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)


def main():
    global start_time
    start_time = datetime.now()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    write_pid()

    logger.info("=" * 55)
    logger.info("  🔥 自动化交易守护进程 v2")
    logger.info(f"  PID: {os.getpid()}")
    logger.info(f"  启动时间: {start_time}")
    logger.info(f"  模式: 全自动无人值守")
    logger.info("=" * 55)

    # 启动线程
    threads = [
        ("每日交易循环", run_daily_cycle),
        ("盘中止损监控", run_stop_loss_monitor),
    ]
    for name, func in threads:
        t = threading.Thread(target=func, daemon=True, name=name)
        t.start()
        logger.info(f"[线程] {name} 已启动")

    logger.info("\n🟢 自动化交易运行中")
    logger.info("   日志: tail -f logs/daemon.log")
    logger.info("   状态: python3 daemon.py --status")
    logger.info("   停止: python3 daemon.py --stop")

    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(10)
    except KeyboardInterrupt:
        signal_handler(None, None)


def show_status():
    status = load_status()
    pid = read_pid()
    running = os.path.exists(f"/proc/{pid}") if pid > 0 else False

    print("\n" + "=" * 55)
    print("  🔥 自动化交易守护进程状态")
    print("=" * 55)
    print(f"  PID: {pid} ({'🟢 运行中' if running else '🔴 已停止'})")
    print(f"  运行时间: {round((datetime.now() - start_time).total_seconds() / 3600, 1)}小时")
    print(f"  最后更新: {status.get('last_data_update','-')}")
    print(f"  最后信号: {status.get('last_signal','-')}")
    print(f"  最后调仓: {status.get('last_rebalance','-')}")
    print(f"  最近权益: ${status.get('last_equity',0):.2f}")
    print(f"  持仓数量: {status.get('last_position_count',0)}只")
    print(f"  最后记录: {status.get('last_pnl_record','-')}")
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
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
                print("✅ 守护进程已停止")
            except ProcessLookupError:
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
        else:
            print("⚠️ 没有运行的守护进程")
    elif "--daemon" in args:
        # Docker 环境：直接前台运行（由 docker restart policy 管理）
        write_pid()
        main()
    else:
        main()
