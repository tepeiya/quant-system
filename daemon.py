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

# ====== 日志：强制用 /tmp/ 保证 Docker 容器里一定有写权限 ======
LOG_DIR = "/tmp/quant_daemon_logs"
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
logger.info(f"日志目录: {LOG_DIR}")

# ====== PID/STATUS 文件：优先用 /tmp/ 避免权限问题 ======
PID_FILE = "/tmp/quant_daemon.pid"
STATUS_FILE = "/tmp/quant_daemon_status.json"
shutdown_event = threading.Event()
start_time = datetime.now()

# 同时兼容旧路径 config/ 下的文件（如果可写就也写一份）
FALLBACK_PID_FILE = "config/daemon.pid"
FALLBACK_STATUS_FILE = "config/daemon_status.json"


# ====== 状态管理 ======

def save_status(**updates):
    data = {}
    for sf in [STATUS_FILE, FALLBACK_STATUS_FILE]:
        try:
            if os.path.exists(sf):
                with open(sf) as f:
                    data = json.load(f)
                    break
        except:
            pass
    data.update(updates)
    for sf in [STATUS_FILE, FALLBACK_STATUS_FILE]:
        try:
            os.makedirs(os.path.dirname(sf) or ".", exist_ok=True)
            with open(sf, "w") as f:
                json.dump(data, f, indent=2)
        except:
            pass


def load_status() -> dict:
    for sf in [STATUS_FILE, FALLBACK_STATUS_FILE]:
        try:
            if os.path.exists(sf):
                with open(sf) as f:
                    return json.load(f)
        except:
            pass
    return {}


def write_pid():
    for pf in [PID_FILE, FALLBACK_PID_FILE]:
        try:
            os.makedirs(os.path.dirname(pf) or ".", exist_ok=True)
            with open(pf, "w") as f:
                f.write(str(os.getpid()))
            if pf == PID_FILE:
                logger.info(f"PID 文件已写入: {pf} -> {os.getpid()}")
        except Exception as e:
            if pf == PID_FILE:
                logger.error(f"PID 文件写入失败 {pf}: {e}")


def read_pid() -> int:
    for pf in [PID_FILE, FALLBACK_PID_FILE]:
        try:
            if os.path.exists(pf):
                with open(pf) as f:
                    return int(f.read().strip())
        except:
            pass
    return 0


def clean_pid():
    for pf in [PID_FILE, FALLBACK_PID_FILE]:
        try:
            if os.path.exists(pf):
                os.remove(pf)
        except:
            pass


# ====== 每日交易循环 ======

def run_daily_cycle():
    logger.info("[主循环] 启动，每天美东时间9:00-9:35执行交易流程（夏令时=北京时间22:30-23:05）")
    # 夏令时 美东=北京时间-12
    DATA_HOUR = 22   # 北京时间22:00 = 美东10:00（数据更新）
    SIGNAL_HOUR = 22  # 北京时间22:30 = 美东10:30（信号生成）
    SIGNAL_MIN = 30
    REBAL_HOUR = 22   # 北京时间23:05 = 美东11:05（调仓）
    REBAL_MIN = 35

    while not shutdown_event.is_set():
        now = datetime.now()

        if now.weekday() >= 5:
            next_monday = now + timedelta(days=(7 - now.weekday()))
            next_run = next_monday.replace(hour=DATA_HOUR, minute=0, second=0, microsecond=0)
            wait = (next_run - now).total_seconds()
            logger.info(f"[主循环] 周末跳过，下次运行: {next_run}")
            shutdown_event.wait(min(wait, 3600))
            continue

        next_start = now.replace(hour=DATA_HOUR, minute=0, second=0, microsecond=0)
        if now >= next_start:
            next_start += timedelta(days=1)

        wait_seconds = (next_start - now).total_seconds()
        if wait_seconds > 0 and wait_seconds < 86400:
            logger.info(f"[主循环] 下次交易流程: {next_start} (等待{wait_seconds/60:.0f}分钟)")
            if shutdown_event.wait(wait_seconds):
                break

        logger.info("=" * 55)
        logger.info("  🔥 开始日交易流程（美东时间）")
        logger.info("=" * 55)

        today_str = now.strftime("%Y-%m-%d")
        save_status(last_cycle=today_str)

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

        now2 = datetime.now().replace(microsecond=0)
        target_signal = now2.replace(hour=SIGNAL_HOUR, minute=SIGNAL_MIN, second=0, microsecond=0)
        if now2 < target_signal:
            wait_sig = (target_signal - now2).total_seconds()
            logger.info(f"  等待信号时间: {wait_sig/60:.0f}分钟")
            if shutdown_event.wait(wait_sig):
                break

        logger.info("[步骤2/3] 生成保守策略信号...")
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
                logger.error(f"  保守信号失败: {r.stderr[-200:]}")
                shutdown_event.wait(60)
                continue
            else:
                save_status(last_signal=str(datetime.now()))
        except Exception as e:
            logger.error(f"  保守信号异常: {e}")
            shutdown_event.wait(60)
            continue

        # ===== 动量激进策略：独立信号生成 =====
        logger.info("[激进策略] 生成动量信号...")
        try:
            r = subprocess.run(
                [sys.executable, "strategy_momentum.py", "--generate"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  [激进] {line.strip()}")
            if r.returncode != 0:
                logger.warning(f"  激进信号失败: {r.stderr[-200:]}")
            else:
                save_status(last_momentum_signal=str(datetime.now()))
        except Exception as e:
            logger.warning(f"  激进信号异常: {e}")

        # ===== 动量激进策略：独立调仓 =====
        logger.info("[激进策略] 自动调仓...")
        try:
            r = subprocess.run(
                [sys.executable, "paper_trader_momentum.py", "--auto"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  [激进] {line.strip()}")
            if r.returncode != 0:
                logger.warning(f"  激进调仓失败: {r.stderr[-200:]}")
            else:
                save_status(last_momentum_rebalance=str(datetime.now()))
        except Exception as e:
            logger.warning(f"  激进调仓异常: {e}")

        now3 = datetime.now().replace(microsecond=0)
        target_rebal = now3.replace(hour=9, minute=35, second=0, microsecond=0)
        if now3 < target_rebal:
            wait_re = (target_rebal - now3).total_seconds()
            logger.info(f"  等待调仓时间: {wait_re/60:.0f}分钟")
            if shutdown_event.wait(wait_re):
                break

        logger.info("[步骤3/3] 保守策略调仓...")
        try:
            r = subprocess.run(
                [sys.executable, "paper_trader.py", "--auto"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  [保守] {line.strip()}")
            if r.returncode != 0:
                logger.error(f"  保守调仓失败: {r.stderr[-200:]}")
            else:
                save_status(last_rebalance=str(datetime.now()))
        except Exception as e:
            logger.error(f"  保守调仓异常: {e}")

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

            # 收盘后发送微信通知
            try:
                from push_notify import send_daily_summary
                send_daily_summary(
                    equity=daily.get("equity", 0),
                    pnl=daily.get("pnl", 0),
                    positions=daily.get("position_count", 0),
                    signal_count=0,
                )
            except:
                pass

            # 收盘后检查缓存是否需要刷新
            try:
                from cache_manager import check_cache_health
                health = check_cache_health()
                if health["needs_refresh"]:
                    logger.info(f"缓存过期({health['age_days']}天), 计划刷新")
                    import threading
                    threading.Thread(target=_refresh_cache_bg, daemon=True).start()
            except:
                pass

        except Exception as e:
            logger.error(f"  收盘记录失败: {e}")

        logger.info(f"✅ 今日交易流程完成，等待明天")


# ====== 日内交易轮询（美股盘中每30分钟） ======

def run_intraday_loop():
    """每30分钟扫描并执行日内交易
    美股夏令时 美东9:30-16:00 = 北京时间21:30-05:00
    """
    interval = 30 * 60
    logger.info("[日内] 轮询线程启动，美东9:30-16:00 (北京21:30-05:00) 每30分钟执行")

    # 启动时立即检查持仓，如果有则强制清仓
    logger.info("[日内] 启动检查持仓...")
    try:
        r = subprocess.run(
            [sys.executable, "intraday_trader.py", "--close-all"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ}
        )
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                logger.info(f"  [日内] {line.strip()}")
    except Exception as e:
        logger.warning(f"  [日内] 启动检查: {e}")

    while not shutdown_event.is_set():
        now = datetime.now()
        if now.weekday() >= 5:
            shutdown_event.wait(3600)
            continue

        hour = now.hour
        minute = now.minute

        # 非美股交易时间跳过（夏令时：北京21:30-05:00）
        if hour >= 5 and hour < 21:
            shutdown_event.wait(1800)
            continue
        if hour == 21 and minute < 30:
            shutdown_event.wait(1800)
            continue
        if hour >= 4 and minute >= 45:
            shutdown_event.wait(3600)
            continue

        logger.info("[日内] 扫描信号...")
        try:
            r = subprocess.run(
                [sys.executable, "intraday.py", "--scan"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip() and "{" not in line and "}" not in line:
                    logger.info(f"  [日内] {line.strip()}")
            save_status(last_intraday_scan=str(datetime.now()))
        except Exception as e:
            logger.warning(f"  [日内] 扫描异常: {e}")

        logger.info("[日内] 执行...")
        try:
            r = subprocess.run(
                [sys.executable, "intraday_trader.py", "--auto"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ}
            )
            for line in r.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  [日内] {line.strip()}")
        except Exception as e:
            logger.warning(f"  [日内] 执行异常: {e}")

        # 收盘前强制清仓（美东15:45 = 北京04:45）
        if hour >= 4 and minute >= 45:
            logger.info("[日内] 收盘前，强制清仓...")
            try:
                r = subprocess.run(
                    [sys.executable, "intraday_trader.py", "--close-all"],
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ}
                )
                for line in r.stdout.strip().split("\n"):
                    if line.strip():
                        logger.info(f"  [日内] {line.strip()}")
            except Exception as e:
                logger.warning(f"  [日内] 清仓异常: {e}")

        shutdown_event.wait(interval)


# ====== 盘中止损监控 ======

def run_stop_loss_monitor():
    """每5分钟检查止损 + 云端止损单"""
    interval = 300
    logger.info("[止损] 盘中监控启动（含云端止损单）")
    cloud_orders_set = False
    while not shutdown_event.is_set():
        try:
            from stop_loss_monitor import check_and_stop
            result = check_and_stop()
            if result:
                logger.warning(f"[止损] 触发{len(result)}笔: {result}")
                save_status(last_stop_loss=str(datetime.now()), stop_triggered=len(result))

            # 云端止损单（每天仅开盘设置一次）
            if not cloud_orders_set:
                try:
                    from alpaca.trading.client import TradingClient
                    from alpaca.trading.requests import StopLossOrderRequest
                    from alpaca.trading.enums import OrderSide, TimeInForce
                    from broker_manager import get_default_broker_id, load_config

                    default_id = get_default_broker_id()
                    cfg = load_config().get(default_id, {})
                    key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
                    secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
                    client = TradingClient(key, secret, paper=cfg.get("paper", True))

                    positions = client.get_all_positions()
                    existing_orders = {o.symbol for o in client.get_orders(status='OPEN')}

                    count = 0
                    for p in positions:
                        sym = p.symbol
                        qty = int(float(p.qty))
                        if qty <= 0 or sym in existing_orders:
                            continue
                        entry = float(p.avg_entry_price)
                        stop_price = round(entry * 0.88, 2)
                        if stop_price > 0:
                            client.submit_order(StopLossOrderRequest(
                                symbol=sym, qty=qty, side=OrderSide.SELL,
                                stop_price=stop_price, time_in_force=TimeInForce.DAY))
                            count += 1
                    if count > 0:
                        logger.info(f"[止损] 已设置{count}个云端止损单")
                    cloud_orders_set = True
                except Exception as e:
                    logger.debug(f"[止损] 云端止损单跳过: {e}")

        except Exception as e:
            logger.debug(f"[止损] 检查跳过: {e}")
        shutdown_event.wait(interval)


def _refresh_cache_bg():
    """后台刷新缓存"""
    try:
        from cache_manager import refresh_if_needed
        refresh_if_needed()
    except:
        pass


# ====== 信号处理 ======

def signal_handler(sig, frame):
    logger.info("收到停止信号，优雅关闭...")
    shutdown_event.set()
    save_status(shutdown=str(datetime.now()))
    clean_pid()
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

    threads = [
        ("每日交易循环", run_daily_cycle),
        ("盘中止损监控", run_stop_loss_monitor),
        ("日内交易轮询", run_intraday_loop),
    ]
    for name, func in threads:
        t = threading.Thread(target=func, daemon=True, name=name)
        t.start()
        logger.info(f"[线程] {name} 已启动")

    logger.info("\n🟢 自动化交易运行中")
    logger.info(f"   日志: tail -f {LOG_DIR}/daemon.log")
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
    running = False
    if pid > 0:
        try:
            os.kill(pid, 0)
            running = True
        except:
            pass

    print("\n" + "=" * 55)
    print("  🔥 自动化交易守护进程状态")
    print("=" * 55)
    print(f"  PID: {pid} ({'🟢 运行中' if running else '🔴 已停止'})")
    elapsed = datetime.now() - start_time if start_time else timedelta(0)
    print(f"  运行时间: {round(elapsed.total_seconds() / 3600, 1)}小时")
    print(f"  最后更新: {status.get('last_data_update','-')}")
    print(f"  最后信号: {status.get('last_signal','-')}")
    print(f"  最后调仓: {status.get('last_rebalance','-')}")
    print(f"  最后止损: {status.get('last_stop_loss','-')}")
    print(f"  最新权益: ${status.get('last_equity',0):.2f}")
    print(f"  日志目录: {LOG_DIR}/daemon.log")
    print("=" * 55)


def stop_daemon():
    pid = read_pid()
    if pid <= 0:
        print("守护进程未运行")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已发送停止信号给 PID {pid}")
    except ProcessLookupError:
        print("守护进程已停止")
        clean_pid()


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop_daemon()
    elif "--status" in sys.argv:
        show_status()
    elif "--daemon" in sys.argv:
        pid = os.fork()
        if pid > 0:
            print(f"守护进程已启动, PID: {pid}")
            sys.exit(0)
        main()
    else:
        main()
