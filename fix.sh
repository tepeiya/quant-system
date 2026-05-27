#!/bin/bash
# M+ 一键修复脚本

cd "$(dirname "$0")"

docker compose down

# 1. 装 fredapi
pip3 install fredapi 2>/dev/null

# 2. 改 Dockerfile
if ! grep -q "fredapi" Dockerfile 2>/dev/null; then
  sed -i 's/flask passlib scipy/flask passlib scipy fredapi/' Dockerfile
fi

# 3. 改 docker-compose
if ! grep -q "FRED_API_KEY" docker-compose.yml 2>/dev/null; then
  sed -i '/ALPACA_SECRET_KEY/a\      - FRED_API_KEY=${FRED_API_KEY}' docker-compose.yml
fi

# 4. 确保 .env 有 FRED_API_KEY
if ! grep -q "FRED_API_KEY" .env 2>/dev/null; then
  echo "FRED_API_KEY=你的FREDKey" >> .env
  echo "⚠️  请在 .env 里填写你的 FRED_API_KEY"
fi

# 5. 构建启动
./start.sh build
./start.sh start

echo "✅ 修复完成，打开 http://localhost:8765"
