#!/bin/sh
# 一键推送到 GitHub
# 用法: sh git_push.sh "提交说明"

set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "${GREEN}========================================${NC}"
echo "${GREEN}  🚀 推送到 GitHub${NC}"
echo "${GREEN}========================================${NC}"
echo ""

# 检查 git 是否安装
if ! command -v git &> /dev/null; then
    echo "${RED}❌ git 未安装，请先安装: apt-get install git${NC}"
    exit 1
fi

# 检查是否已经有 git 仓库
if [ ! -d ".git" ]; then
    echo "${YELLOW}📦 初始化 git 仓库...${NC}"
    git init
fi

# 确认 GitHub 仓库地址
REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE" ]; then
    echo ""
    echo "${YELLOW}⚠️  还没有设置 GitHub 远程仓库${NC}"
    echo ""
    echo "请输入你的 GitHub 仓库地址（比如）："
    echo "  https://github.com/你的用户名/quant-system.git"
    echo ""
    printf "地址: "
    read REPO_URL
    
    if [ -z "$REPO_URL" ]; then
        echo "${RED}❌ 仓库地址不能为空${NC}"
        exit 1
    fi
    
    git remote add origin "$REPO_URL"
    echo "${GREEN}✅ 远程仓库已设置${NC}"
fi

# 提交信息
MSG="${1:-更新量化系统 v2.2}"

echo ""
echo "${YELLOW}📝 提交信息: ${MSG}${NC}"
echo ""

# 添加所有文件（排除敏感文件）
echo "${YELLOW}📦 添加文件...${NC}"
git add \
    --all \
    -- ':!config/users.json' \
    -- ':!config/broker_keys.json' \
    -- ':!config/circuit_breaker.json' \
    -- ':!config/daemon.pid' \
    -- ':!config/daemon_status.json' \
    -- ':!signals/trade_log.json' \
    -- ':!signals/portfolio.json' \
    -- ':!signals/cached_portfolio.json' \
    -- ':!data_cache/spy_cache.pkl' \
    -- ':!env_setup.sh' \
    -- ':!logs/' \
    -- ':!__pycache__/' \
    -- ':!*.pyc' \
    -- ':!*.tar.gz'

echo "${GREEN}✅ 文件已添加${NC}"

# 提交
echo ""
echo "${YELLOW}💾 提交...${NC}"
git commit -m "$MSG"

# 推送到 GitHub
echo ""
echo "${YELLOW}☁️  推送到 GitHub...${NC}"
echo "${YELLOW}   （如果第一次推送，需要输入用户名和密码/Token）${NC}"
echo ""
git push -u origin main 2>&1 || git push -u origin master 2>&1

echo ""
echo "${GREEN}========================================${NC}"
echo "${GREEN}  ✅ 推送成功！${NC}"
echo "${GREEN}========================================${NC}"
echo ""
echo "现在去 https://railway.app 部署："
echo "  1. 登录 Railway（用GitHub账号）"
echo "  2. New Project → Deploy from GitHub repo"
echo "  3. 选择 quant-system 仓库"
echo "  4. 在 Dashboard 设置环境变量"
echo ""
