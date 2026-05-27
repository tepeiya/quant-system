#!/bin/bash
# 查看Alpaca账户状态快捷脚本
# 用法: ./status.sh

KEY="${ALPACA_API_KEY_ID:-}"
SECRET="${ALPACA_SECRET_KEY:-}"

if [ -z "$KEY" ] || [ -z "$SECRET" ]; then
    echo "❌ 请先设置环境变量:"
    echo "   export ALPACA_API_KEY_ID=你的Key"
    echo "   export ALPACA_SECRET_KEY=你的Secret"
    exit 1
fi

echo "==============================================="
echo "  Alpaca 纸交易 - 账户状态"
echo "==============================================="

# 账户信息
echo ""
curl -s -u "$KEY:$SECRET" "https://paper-api.alpaca.markets/v2/account" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"账号:      {d['account_number']}\")
print(f\"状态:      {d['status']}\")
print(f\"现金:      \${float(d['cash']):>10,.2f}\")
print(f\"总权益:    \${float(d['equity']):>10,.2f}\")
print(f\"购买力:    \${float(d['buying_power']):>10,.2f}\")
"

# 持仓
echo ""
echo "📋 持仓:"
curl -s -u "$KEY:$SECRET" "https://paper-api.alpaca.markets/v2/positions" | python3 -c "
import sys, json
positions = json.load(sys.stdin)
if positions:
    print(f\"{'股票':>6} {'数量':>6} {'均价':>8} {'现价':>8} {'市值':>10} {'PnL%':>8}\")
    print(f\"{'-'*50}\")
    for p in positions:
        pnl = float(p['unrealized_pl_pct']) * 100
        print(f\"  {p['symbol']:>6} {int(p['qty']):>6} \${float(p['avg_entry_price']):>7.2f} \${float(p['current_price']):>7.2f} \${float(p['market_value']):>9,.0f} {pnl:>+7.2f}%\")
else:
    print(\"  空仓\")
"

# 今日交易
echo ""
echo "📝 今日交易:"
today=$(date +%Y-%m-%d)
curl -s -u "$KEY:$SECRET" "https://paper-api.alpaca.markets/v2/orders?limit=10&status=closed" | python3 -c "
import sys, json
orders = json.load(sys.stdin)
today_orders = [o for o in orders if o.get('filled_at', '').startswith('$today')]
if today_orders:
    for o in today_orders:
        print(f\"  {o['side']:>4} {o['symbol']:>6} x{o['qty']:>4} @ \${float(o['filled_avg_price']):>7.2f} ({o['filled_at'][11:16]})\")
else:
    print(\"  今日无交易\")
"
echo ""
echo "==============================================="
