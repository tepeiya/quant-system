#!/bin/bash
set -e

echo "========================================="
echo "  量化交易系统 - 一键部署脚本"
echo "========================================="
echo ""

DEPLOY_DIR="/opt/quant_system"
SERVICE_NAME="quant-web"
PORT=8765

echo "[1/8] 检查系统环境..."
if [ "$(id -u)" != "0" ]; then
    echo "请使用 root 用户运行此脚本"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "安装 Python3..."
    apt-get update -qq
    apt-get install -y python3 python3-pip python3-venv
fi

PYTHON_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "  Python 版本: $PYTHON_VERSION"

echo ""
echo "[2/8] 安装系统依赖..."
apt-get install -y nginx supervisor curl wget 2>/dev/null || true

echo ""
echo "[3/8] 创建部署目录..."
mkdir -p $DEPLOY_DIR
echo "  部署目录: $DEPLOY_DIR"

echo ""
echo "[4/8] 解压系统文件..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ -f "$SCRIPT_DIR/quant_system_full.tar.gz" ]; then
    echo "  从 quant_system_full.tar.gz 解压..."
    tar xzf "$SCRIPT_DIR/quant_system_full.tar.gz" -C $DEPLOY_DIR
elif [ -f "$SCRIPT_DIR/quant_system.tar.gz" ]; then
    echo "  从 quant_system.tar.gz 解压..."
    tar xzf "$SCRIPT_DIR/quant_system.tar.gz" -C $DEPLOY_DIR
else
    echo "  错误: 未找到部署包"
    echo "  请确保 quant_system_full.tar.gz 或 quant_system.tar.gz 与此脚本在同一目录"
    exit 1
fi

echo "  文件解压完成"
ls -la $DEPLOY_DIR/ | head -10

echo ""
echo "[5/8] 安装 Python 依赖..."
cd $DEPLOY_DIR

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip -q

if [ -f "requirements.txt" ]; then
    echo "  安装依赖包 (需要几分钟)..."
    pip install -r requirements.txt -q 2>&1 | tail -5
    echo "  依赖安装完成"
else
    echo "  安装核心依赖..."
    pip install flask pandas numpy requests bcrypt -q 2>&1 | tail -5
fi

echo ""
echo "[6/8] 初始化管理员账户..."
cd $DEPLOY_DIR
source venv/bin/activate

python3 -c "
import os, json, bcrypt

os.makedirs('config/users', exist_ok=True)

password = 'admin123'.encode('utf-8')
hashed = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')

users = {
    'admin': {
        'username': 'admin',
        'password': hashed,
        'role': 'admin',
        'created_at': __import__('datetime').datetime.now().isoformat()
    }
}

with open('config/users.json', 'w') as f:
    json.dump(users, f, indent=2, ensure_ascii=False)

print('  管理员账户创建成功: admin / admin123')
"

if [ ! -f "config/secret_key.txt" ]; then
    python3 -c "
import secrets
with open('config/secret_key.txt', 'w') as f:
    f.write(secrets.token_hex(32))
print('  生成密钥文件')
"
fi

echo ""
echo "[7/8] 配置系统服务..."

cat > /etc/supervisor/conf.d/quant-web.conf << EOF
[program:quant-web]
command=$DEPLOY_DIR/venv/bin/python $DEPLOY_DIR/web_app.py
directory=$DEPLOY_DIR
user=root
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/quant-web.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="$DEPLOY_DIR/venv/bin",HOME="/root"
EOF

supervisorctl reread 2>/dev/null || true
supervisorctl update 2>/dev/null || true
supervisorctl restart quant-web 2>/dev/null || {
    echo "  supervisor 不可用，使用 nohup 启动..."
    pkill -f "python.*web_app.py" 2>/dev/null || true
    nohup $DEPLOY_DIR/venv/bin/python $DEPLOY_DIR/web_app.py > /var/log/quant-web.log 2>&1 &
    echo "  服务已启动 (PID: $!)"
}

sleep 3

echo ""
echo "[8/8] 验证服务..."
echo "  等待服务启动..."

for i in {1..10}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$PORT/auth/login 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ] || [ "$STATUS" = "302" ]; then
        echo "  ✅ 服务启动成功 (HTTP $STATUS)"
        break
    fi
    echo "  等待中... ($i/10) 状态: $STATUS"
    sleep 2
done

IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo "========================================="
echo "  部署完成！"
echo "========================================="
echo ""
echo "  🌐 访问地址:"
echo "     外网: http://$IP_ADDR:$PORT"
echo "     本地: http://127.0.0.1:$PORT"
echo ""
echo "  👤 登录账户:"
echo "     用户名: admin"
echo "     密  码: admin123"
echo ""
echo "  📁 部署目录: $DEPLOY_DIR"
echo "  📝 服务日志: tail -f /var/log/quant-web.log"
echo "  🔄 重启服务: supervisorctl restart quant-web"
echo ""
echo "  💡 首次使用请执行数据预热:"
echo "     cd $DEPLOY_DIR && source venv/bin/activate"
echo "     python warmup_global.py"
echo ""
