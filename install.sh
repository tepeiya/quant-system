#!/bin/bash
# ============================================================
#  M+ 量化系统 — VPS 一键安装脚本
#  在干净的 Ubuntu/Debian VPS 上：
#    1. 安装 Docker 和 Docker Compose
#    2. 克隆最新代码
#    3. 引导填写 API Key
#    4. 构建并启动容器
#    5. 设置开机自启
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
info() { echo -e "${CYAN}[i]${NC} $1"; }

BANNER="${CYAN}
╔══════════════════════════════════════════╗
║       📊 M+ 量化系统 — 一键部署          ║
║     Multi-Factor Momentum+ on Docker     ║
╚══════════════════════════════════════════╝${NC}"

echo -e "$BANNER"
echo ""

# --------------------------------------------------
# 检测系统
# --------------------------------------------------
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
    else
        OS=$(uname -s)
    fi
    echo "$OS $VER"
}

# --------------------------------------------------
# 步骤 1: 安装 Docker
# --------------------------------------------------
install_docker() {
    info "检查 Docker 安装状态..."

    if command -v docker &>/dev/null; then
        log "Docker 已安装: $(docker --version)"
    else
        warn "Docker 未安装，开始安装..."
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        log "Docker 安装完成: $(docker --version)"
    fi

    if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
        log "Docker Compose 已安装"
    else
        warn "安装 Docker Compose..."
        DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
        mkdir -p "$DOCKER_CONFIG/cli-plugins"
        curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
        chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
        log "Docker Compose 安装完成"
    fi

    # 添加当前用户到 docker 组
    if ! groups "$USER" | grep -q docker; then
        sudo usermod -aG docker "$USER" 2>/dev/null || true
        warn "已将 $USER 加入 docker 组，可能需要重新登录生效"
    fi
}

# --------------------------------------------------
# 步骤 2: 克隆代码
# --------------------------------------------------
clone_repo() {
    local target_dir="$1"
    if [ -d "$target_dir/.git" ]; then
        log "代码已存在，拉取最新更新..."
        cd "$target_dir"
        git pull origin main 2>/dev/null || true
    else
        info "克隆 M+ 代码到 $target_dir ..."
        git clone https://github.com/tepeiya/quant-system.git "$target_dir"
        cd "$target_dir"
        log "代码克隆完成"
    fi
}

# --------------------------------------------------
# 步骤 3: 配置 .env
# --------------------------------------------------
setup_env() {
    local target_dir="$1"
    cd "$target_dir"

    if [ -f .env ]; then
        warn ".env 文件已存在，跳过配置"
        info "如需重新配置，请删除 .env 文件后重新运行脚本"
        return
    fi

    echo ""
    echo -e "${YELLOW}══════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  配置 API Key（必填）${NC}"
    echo -e "${YELLOW}══════════════════════════════════════════════${NC}"
    echo ""

    cat > .env << 'EOF'
# M+ 量化系统环境变量
# 时区
TZ=Asia/Shanghai

# --- Alpaca 纸交易（必填）---
# 在 https://app.alpaca.markets/paper 获取
ALPACA_API_KEY_ID=
ALPACA_SECRET_KEY=

# --- Tiingo 数据源（必填）---
# 在 https://api.tiingo.com 注册获取免费 Key
TIINGO_API_KEY=

# --- FRED 宏观数据（可选）---
# 在 https://fred.stlouisfed.org/docs/api/api_key.html 获取
FRED_API_KEY=

# --- PushPlus 微信推送（可选）---
PUSHPLUS_TOKEN=
EOF

    echo -e "${CYAN}📝 请填写你的 API Key${NC}"
    echo ""

    read -p "👉 Alpaca API Key ID      (留空跳过): " key_id
    read -p "👉 Alpaca Secret Key      (留空跳过): " secret_key
    read -p "👉 Tiingo API Key         (留空跳过): " tiingo_key
    read -p "👉 FRED API Key           (留空跳过): " fred_key
    read -p "👉 PushPlus Token         (留空跳过): " pushplus_token

    if [ -n "$key_id" ]; then
        sed -i "s/^ALPACA_API_KEY_ID=$/ALPACA_API_KEY_ID=$key_id/" .env
    fi
    if [ -n "$secret_key" ]; then
        sed -i "s/^ALPACA_SECRET_KEY=$/ALPACA_SECRET_KEY=$secret_key/" .env
    fi
    if [ -n "$tiingo_key" ]; then
        sed -i "s/^TIINGO_API_KEY=$/TIINGO_API_KEY=$tiingo_key/" .env
    fi
    if [ -n "$fred_key" ]; then
        sed -i "s/^FRED_API_KEY=$/FRED_API_KEY=$fred_key/" .env
    fi
    if [ -n "$pushplus_token" ]; then
        sed -i "s/^PUSHPLUS_TOKEN=$/PUSHPLUS_TOKEN=$pushplus_token/" .env
    fi

    log "环境变量配置完成"
}

# --------------------------------------------------
# 步骤 4: 构建并启动
# --------------------------------------------------
build_and_start() {
    local target_dir="$1"
    cd "$target_dir"

    echo ""
    info "构建 Docker 镜像（首次约 3-5 分钟）..."

    # 检查 .env 是否至少填了 Alpaca
    if grep -q "ALPACA_API_KEY_ID=.\+" .env 2>/dev/null && grep -q "ALPACA_SECRET_KEY=.\+" .env 2>/dev/null; then
        log "Alpaca Key 已配置"
    else
        warn "Alpaca Key 未完整配置，系统启动后需在设置页面补充"
    fi

    docker compose build 2>&1 | tail -5
    log "Docker 镜像构建完成"

    docker compose up -d
    log "容器已启动"
}

# --------------------------------------------------
# 步骤 5: 验证
# --------------------------------------------------
verify() {
    local target_dir="$1"
    cd "$target_dir"

    echo ""
    info "验证部署状态..."

    sleep 3

    # 检查容器是否运行
    if docker compose ps 2>/dev/null | grep -q "Up"; then
        log "容器运行中"
    else
        err "容器未正常启动"
        warn "查看日志: cd $target_dir && docker compose logs"
        return
    fi

    # 检查 HTTP 响应
    local port=$(grep -E "^PORT=" .env 2>/dev/null | cut -d= -f2)
    port=${port:-8765}

    if curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/login 2>/dev/null | grep -q 200; then
        log "Web 面板响应正常"
    else
        warn "Web 面板暂时无法访问（可能在初始化中）"
        warn "稍后重试: curl http://localhost:$port/login"
    fi

    echo ""
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✅ M+ 量化系统部署完成！${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  访问地址: ${CYAN}http://$(curl -s ifconfig.me 2>/dev/null || echo '你的VPS_IP'):$port${NC}"
    echo -e "  本地访问: ${CYAN}http://localhost:$port${NC}"
    echo ""
    echo -e "  默认管理员账号: ${YELLOW}admin${NC}"
    echo -e "  默认管理员密码: ${YELLOW}admin123${NC}"
    echo ""
    echo -e "  ${YELLOW}⚠ 首次登录后请立即修改密码！${NC}"
    echo ""
    echo -e "  ${CYAN}常用命令：${NC}"
    echo -e "    查看日志:  cd $target_dir && docker compose logs -f"
    echo -e "    重启:      cd $target_dir && docker compose restart"
    echo -e "    停止:      cd $target_dir && docker compose down"
    echo -e "    升级:      cd $target_dir && git pull && docker compose up -d --build"
    echo ""
}

# --------------------------------------------------
# 主流程
# --------------------------------------------------
main() {
    echo -e "${CYAN}系统检测: $(detect_os)${NC}"
    echo ""

    # 安装目录
    INSTALL_DIR="${1:-$HOME/m-plus}"
    if [ "$INSTALL_DIR" = "." ]; then
        INSTALL_DIR="$PWD"
    fi

    # 需要 sudo 的操作
    if [ "$EUID" -ne 0 ]; then
        warn "部分操作需要 root 权限（安装 Docker），会通过 sudo 执行"
        echo ""
    fi

    # 步骤 1: 安装 Docker
    install_docker

    # 步骤 2: 克隆代码
    clone_repo "$INSTALL_DIR"

    # 步骤 3: 配置 .env
    setup_env "$INSTALL_DIR"

    # 步骤 4: 构建并启动
    build_and_start "$INSTALL_DIR"

    # 步骤 5: 验证
    verify "$INSTALL_DIR"
}

main "$@"
