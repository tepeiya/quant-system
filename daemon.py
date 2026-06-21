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

import os, sys, json, logging, time, signal, threading
from datetime import datetime, timedelta

# ====== 日志：写入 logs/ 目录（Docker卷挂载，重启不丢失） ======
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
    DATA_HOUR = 21   # 北京时间21:00 = 美东09:00（数据更新）
    SIGNAL_HOUR = 21  # 北京时间21:30 = 美东09:30（信号生成）
    SIGNAL_MIN = 30
    REBAL_HOUR = 21   # 北京时间21:35 = 美东09:35（调仓）
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
        logger.info("  🔥 开始日交易流程（美东时间09:00~09:35）")
        logger.info("=" * 55)

        today_str = now.strftime("%Y-%m-%d")
        save_status(last_cycle=today_str)

        logger.info("[步骤1/3] 数据服务更新行情...")
        try:
            from warmup_data import warmup
            r = warmup(batch_size=80)
            from data_prod import load_price_cache
            cache = load_price_cache()
            logger.info(f"  缓存: {len(cache)}只股票 (本次获取{r.get('fetched',0)}只, 剩余{r.get('remaining',0)}只)")
        except Exception as e:
            logger.error(f"  数据更新异常: {e}")

        now2 = datetime.now().replace(microsecond=0)
        target_signal = now2.replace(hour=SIGNAL_HOUR, minute=SIGNAL_MIN, second=0, microsecond=0)
        if now2 < target_signal:
            wait_sig = (target_signal - now2).total_seconds()
            logger.info(f"  等待信号时间({target_signal.strftime('%H:%M')}): {wait_sig/60:.0f}分钟")
            if shutdown_event.wait(wait_sig):
                break

        logger.info("[步骤2/3] === 通过插件系统生成信号 ===")
        try:
            from plugin_loader import load_all, run_all
            # 确保插件已加载
            if not load_all():
                logger.warning("  插件加载为空，重试...")
                load_all()

            results = run_all()
            total_signals = sum(len(v) for v in results.values())
            save_status(last_signal=str(datetime.now()), plugin_results=str({k: len(v) for k, v in results.items()}))
            logger.info(f"  ✅ 插件全部执行完成，共 {total_signals} 条信号")
            for name, signals in results.items():
                logger.info(f"    {name}: {len(signals)} 条")
        except Exception as e:
            logger.error(f"  插件系统执行异常: {e}")
            logger.info("  [回退] 直接调用策略...")
            # 回退到旧逻辑
            try:
                from daily_signal import generate_signals
                generate_signals()
            except Exception as e2:
                logger.error(f"  回退保守信号失败: {e2}")
            try:
                from strategy_momentum import generate_signals
                from data_prod import load_price_cache, compute_indicators
                cache = load_price_cache()
                for tkr in list(cache.keys()):
                    df = cache[tkr]
                    if df is not None and "Momentum_12M" not in df.columns:
                        cache[tkr] = compute_indicators(df)
                generate_signals(cache, top_n=15)
            except Exception as e2:
                logger.error(f"  回退动量信号失败: {e2}")
            shutdown_event.wait(60)
            continue

        # ===== 通过执行器自动调仓 =====
        logger.info("[步骤3/3] 通过执行器自动下单...")
        try:
            from trade_executor import TradeExecutor
            ex = TradeExecutor()
            results = ex.run_once(dry_run=False)
            save_status(last_rebalance=str(datetime.now()), executor_results=str(len(results)))
            logger.info(f"  ✅ 执行器自动处理 {len(results)} 笔交易意图")
            if results:
                for r in results:
                    logger.info(f"    [{r['status']}] {r.get('side','')} {r.get('ticker','')} x{r.get('qty',0)}")
        except Exception as e:
            logger.warning(f"  执行器自动交易异常: {e}")
            logger.info("  [回退] 使用旧调仓逻辑...")
            try:
                from paper_trader_momentum import execute_rebalance
                execute_rebalance(auto=True)
                save_status(last_momentum_rebalance=str(datetime.now()))
                logger.info("  ✅ 动量调仓完成(回退)")
            except Exception as e2:
                logger.warning(f"  动量调仓(回退)失败: {e2}")
            try:
                from paper_trader import rebalance
                rebalance(auto=True)
                save_status(last_rebalance=str(datetime.now()))
                logger.info("  ✅ 保守调仓完成(回退)")
            except Exception as e2:
                logger.warning(f"  保守调仓(回退)失败: {e2}")

        logger.info("[收盘] 记录今日权益...")
        try:
            from alpaca.trading.client import TradingClient
            from broker_manager import load_config, get_default_broker_id
            cfg = load_config().get(get_default_broker_id(), {})
            key = os.environ.get(cfg.get("env_key_id", "ALPACA_API_KEY_ID"), "")
            secret = os.environ.get(cfg.get("env_secret", "ALPACA_SECRET_KEY"), "")
            if key and secret:
                client_t = TradingClient(key, secret, paper=cfg.get("paper", True))
                acct = client_t.get_account()
                equity = float(acct.equity)
                cash_amt = float(acct.cash)
                positions_count = len(client_t.get_all_positions())
                save_status(
                    last_equity=equity,
                    last_cash=cash_amt,
                    last_position_count=positions_count,
                    last_pnl_record=str(datetime.now()),
                )
                logger.info(f"  权益: ${equity:.2f}, 现金: ${cash_amt:.2f}, 持仓: {positions_count}只")

                # 收盘后发送微信通知
                try:
                    from push_notify import send_daily_summary
                    send_daily_summary(
                        equity=equity,
                        pnl=equity - float(acct.last_equity),
                        positions=positions_count,
                        signal_count=0,
                    )
                except Exception as push_e:
                    logger.debug(f"推送跳过: {push_e}")
            else:
                logger.warning("  API Key未配置，跳过权益记录")

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
    """每15分钟扫描并执行日内交易
    美股夏令时 美东9:30-16:00 = 北京时间21:30-05:00
    """
    # 从配置文件读取扫描间隔，默认15分钟
    try:
        cfg_path = "config/intraday_config.json"
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                _cfg = json.load(f)
                interval_min = int(_cfg.get("scan_interval_minutes", 15))
        else:
            interval_min = 15
    except:
        interval_min = 15
    interval = max(interval_min, 5) * 60  # 最小5分钟
    logger.info(f"[日内] 轮询线程启动，美东9:30-16:00 (北京21:30-05:00) 每{interval_min}分钟执行")

    # 启动时跳过一天，避免重启后立刻误开仓
    skip_next = True

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

        logger.info("[日内] 插件扫描+执行器下单...")
        try:
            # 通过插件系统运行日内策略
            from plugin_loader import get_loader
            loader = get_loader()
            intraday_plugin = loader.get_plugin("intraday")
            if intraday_plugin and intraday_plugin.enabled:
                signals = intraday_plugin.generate_signals()
                logger.info(f"  [日内] 插件执行完成: {len(signals or [])}只候选")
                save_status(last_intraday_scan=str(datetime.now()))
            else:
                logger.warning("  [日内] 插件未启用，跳过")
        except Exception as e:
            logger.warning(f"  [日内] 插件扫描异常: {e}")
            # 回退旧逻辑
            try:
                from intraday import scan_intraday_signals as scan_intraday
                scan_intraday()
                save_status(last_intraday_scan=str(datetime.now()))
            except Exception as e2:
                logger.debug(f"  [日内] 回退扫描跳过: {e2}")

        # 通过执行器处理总线上的日内信号
        try:
            from trade_executor import TradeExecutor
            ex = TradeExecutor()
            results = ex.run_once(dry_run=False)
            logger.info(f"  [日内] 执行器处理 {len(results)} 笔")
        except Exception as e:
            logger.debug(f"  [日内] 执行器交易跳过: {e}")
            # 回退旧逻辑
            try:
                from intraday_trader import check_stop_loss
                check_stop_loss()
            except:
                pass
            try:
                from intraday_trader import execute_intraday
                execute_intraday(auto=True)
                logger.info("  [日内] (回退)执行完成")
            except:
                pass

        # 收盘前强制清仓（美东15:45 = 北京04:45）
        if hour >= 4 and minute >= 45:
            logger.info("[日内] 收盘前，强制清仓...")
            try:
                from intraday_trader import close_all
                close_all(auto=True)
                logger.info("  [日内] 清仓完成")
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
