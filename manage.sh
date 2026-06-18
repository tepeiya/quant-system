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
  sync)
    echo "🔄 一键同步代码到 VPS..."
    VPS_IP="${VPS_IP:-103.236.94.93}"
    VPS_PORT="${VPS_PORT:-22}"
    VPS_USER="${VPS_USER:-root}"
    VPS_PASS="${VPS_PASS:-}"

    if [ -z "$VPS_PASS" ]; then
      echo "⚠️  请设置 VPS_PASS 环境变量"
      echo "   export VPS_PASS='your_password'"
      exit 1
    fi

    echo "  1. 推送代码到 GitHub..."
    git push origin main 2>/dev/null || echo "  ⚠️ GitHub 推送失败，继续..."
    
    echo "  2. 复制文件到 VPS..."
    sshpass -p "$VPS_PASS" scp -P "$VPS_PORT" -o StrictHostKeyChecking=no \
      strategy_vector.py strategy_momentum.py intraday.py intraday_trader.py \
      daemon.py daily_signal.py push_notify.py \
      web_app.py web/blueprints/*.py web/templates/*.html \
      "${VPS_USER}@${VPS_IP}:/root/m-plus/" 2>/dev/null || true

    echo "  3. 复制到容器并重启..."
    sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no -p "$VPS_PORT" \
      "${VPS_USER}@${VPS_IP}" "
        for f in strategy_vector.py strategy_momentum.py daemon.py intramomentum.py push_notify.py; do
          docker cp /root/m-plus/\$f m-plus-m-plus-1:/app/\$f 2>/dev/null
        done
        docker cp /root/m-plus/web/blueprints/ m-plus-m-plus-1:/app/web/ 2>/dev/null
        docker cp /root/m-plus/web/templates/ m-plus-m-plus-1:/app/web/ 2>/dev/null
        docker restart m-plus-m-plus-1
      "
    echo "✅ 同步完成"
    ;;
  *)
    echo "用法: sh manage.sh {start|stop|restart|status|logs|signal|rebalance|evolve}"
    exit 1
    ;;
esac
