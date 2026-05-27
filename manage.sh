#!/bin/sh
# 量化系统生产管理脚本
# 用法: sh manage.sh {start|stop|restart|status|logs|signal}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

. ./env_setup.sh

case "$1" in
  start)
    echo "🚀 启动量化系统..."
    echo "  1. 启动守护进程 (止损/熔断/信号/再平衡)"
    python3 daemon.py --daemon
    sleep 2
    echo "  2. 检查状态"
    python3 daemon.py --status
    ;;
  stop)
    echo "🛑 停止量化系统..."
    python3 daemon.py --stop
    # 也停了遗留的Web进程
    pkill -f "python3 web_app" 2>/dev/null || true
    echo "✅ 已停止"
    ;;
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
  status)
    echo "📊 系统状态:"
    python3 daemon.py --status
    echo ""
    echo "📋 进程列表:"
    ps aux | grep -E "daemon|web_app" | grep -v grep || echo "  无运行进程"
    ;;
  logs)
    tail -f logs/daemon.log
    ;;
  signal)
    echo "⚡ 手动生成今日信号..."
    python3 daily_signal.py
    ;;
  rebalance)
    echo "⚡ 手动执行再平衡..."
    python3 paper_trader.py --rebalance --auto
    ;;
  evolve)
    echo "🧠 手动执行因子进化..."
    python3 factor_learner.py --apply
    ;;
  *)
    echo "用法: sh manage.sh {start|stop|restart|status|logs|signal|rebalance|evolve}"
    exit 1
    ;;
esac
