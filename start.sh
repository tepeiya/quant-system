#!/bin/bash
# M+ 一键启动
cd "$(dirname "$0")"

case "${1:-start}" in
  build)
    docker compose build
    echo "✅ 构建完成"
    ;;
  start)
    if [ ! -f .env ]; then
      echo "创建 .env 文件..."
      echo "ALPACA_API_KEY_ID=" > .env
      echo "ALPACA_SECRET_KEY=" >> .env
      echo "请编辑 .env 填入你的API Key"
      exit 1
    fi
    docker compose up -d
    echo "✅ M+ 已启动: http://localhost:8765"
    ;;
  stop)
    docker compose down
    echo "✅ M+ 已停止"
    ;;
  logs)
    docker compose logs -f
    ;;
  rebuild)
    docker compose run --rm m-plus python3 -c "
from data_prod import get_tickers, fetch_prices, compute_indicators
import pickle
tickers = get_tickers()[:200]
prices = fetch_prices(tickers)
for t in prices: prices[t] = compute_indicators(prices[t])
with open('data_cache/prices.pkl','wb') as f: pickle.dump(prices, f)
print(f'缓存重建完成: {len(prices)}只')
"
    ;;
  *)
    echo "用法: ./start.sh [build|start|stop|logs|rebuild]"
    ;;
esac
