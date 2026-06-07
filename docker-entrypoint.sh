#!/bin/sh
# docker-entrypoint.sh
# 同时启动 Web 面板和自动交易守护进程

# 启动 Web (gunicorn)
echo ">>> 启动 Web 面板..."
gunicorn web_app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-level info &

# 后台等待 Web 就绪后启动 Daemon
(
  for i in $(seq 1 30); do
    if curl -s -o /dev/null http://127.0.0.1:$PORT/login 2>/dev/null; then
      echo ">>> Web 就绪，启动自动交易守护进程..."
      python3 /app/daemon.py
      break
    fi
    sleep 2
  done
) &

# 等待任意子进程退出
wait -n
