#!/bin/sh
# 一键健康自检脚本

BASE="${1:-http://localhost:8765}"
echo "== Quant System Health Check =="
echo "BASE: $BASE"

check_url() {
  name="$1"
  url="$2"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$url")
  if [ "$code" = "200" ] || [ "$code" = "302" ]; then
    echo "✅ $name -> $code"
  else
    echo "❌ $name -> $code"
  fi
}

check_url "登录页" "$BASE/login"
check_url "券商页" "$BASE/brokers/"
check_url "设置页" "$BASE/settings/"
check_url "健康接口" "$BASE/api/health/full"

# API登录并校验核心接口
LOGIN_JSON=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d '{"username":"admin","password":"quant123"}')
echo "登录结果: $LOGIN_JSON"

echo "\n提示：若登录成功后页面仍报网络错误，清理浏览器缓存后重试。"
