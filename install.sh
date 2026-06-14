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

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
info() { echo -e "${CYAN}[i]${NC} $1"; }

# ----- Docker 权限自检 -----
if ! docker ps &>/dev/null 2>&1; then
    if sudo docker ps &>/dev/null 2>&1; then
        warn "当前用户无 Docker 权限，自动使用 sudo"
        DOCKER="sudo docker"
        COMPOSE="sudo docker compose"
    else
        warn "Docker 无权限，尝试将 $USER 加入 docker 组..."
        sudo usermod -aG docker "$USER" 2>/dev/null || true
        warn "已添加，请退出 SSH 重新登录后重试，或使用: curl -sSL ... | sudo bash"
        exit 1
    fi
else
    DOCKER="docker"
    COMPOSE="docker compose"
fi

echo -e "${CYAN}
╔══════════════════════════════════════════╗
║       📊 M+ 量化系统 — 一键部署          ║
║     Multi-Factor Momentum+ on Docker     ║
╚══════════════════════════════════════════╝${NC}"
echo ""

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release; echo "$ID $VERSION_ID"
    else
        uname -s
    fi
}

# ----- 1. 安装 Docker -----
install_docker() {
    info "检查 Docker 安装状态..."
    if command -v docker &>/dev/null; then
        log "Docker 已安装: $($DOCKER --version)"
    else
        warn "Docker 未安装，开始安装..."
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        log "Docker 安装完成: $($DOCKER --version)"
    fi
    if $COMPOSE version &>/dev/null 2>&1; then
        log "Docker Compose 已安装"
    else
        warn "安装 Docker Compose..."
        DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
        mkdir -p "$DOCKER_CONFIG/cli-plugins"
        curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
        chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
        log "Docker Compose 安装完成"
    fi
}

# ----- 2. 克隆代码 -----
clone_repo() {
    local dir="$1"
    if [ -d "$dir/.git" ]; then
        log "代码已存在，拉取最新更新..."
        cd "$dir" && git pull origin main 2>/dev/null || true
    else
        info "克隆 M+ 代码到 $dir ..."
        git clone https://github.com/tepeiya/quant-system.git "$dir"
        cd "$dir"
        log "代码克隆完成"
    fi
}

# ----- 3. 配置 .env -----
setup_env() {
    local dir="$1"; cd "$dir"
    if [ -f .env ]; then
        warn ".env 文件已存在，跳过配置"
        return
    fi

    echo ""
    echo -e "${YELLOW}══════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  配置 API Key（必填）${NC}"
    echo -e "${YELLOW}══════════════════════════════════════════════${NC}"
    echo ""

    cat > .env << 'EOF'
TZ=Asia/Shanghai
ALPACA_API_KEY_ID=
ALPACA_SECRET_KEY=
TIINGO_API_KEY=
FRED_API_KEY=
PUSHPLUS_TOKEN=
EOF

    read -p "Alpaca API Key ID (留空跳过): " v
    [ -n "$v" ] && sed -i "s/^ALPACA_API_KEY_ID=$/ALPACA_API_KEY_ID=$v/" .env
    read -p "Alpaca Secret Key (留空跳过): " v
    [ -n "$v" ] && sed -i "s/^ALPACA_SECRET_KEY=$/ALPACA_SECRET_KEY=$v/" .env
    read -p "Tiingo API Key    (留空跳过): " v
    [ -n "$v" ] && sed -i "s/^TIINGO_API_KEY=$/TIINGO_API_KEY=$v/" .env
    read -p "FRED API Key      (留空跳过): " v
    [ -n "$v" ] && sed -i "s/^FRED_API_KEY=$/FRED_API_KEY=$v/" .env
    read -p "PushPlus Token    (留空跳过): " v
    [ -n "$v" ] && sed -i "s/^PUSHPLUS_TOKEN=$/PUSHPLUS_TOKEN=$v/" .env
    log "环境变量配置完成"
}

# ----- 4. 构建并启动 -----
build_and_start() {
    local dir="$1"; cd "$dir"
    echo ""
    info "构建 Docker 镜像（首次约 3-5 分钟）..."
    $COMPOSE build 2>&1 | tail -5
    log "Docker 镜像构建完成"
    $COMPOSE up -d
    log "容器已启动"
}

# ----- 5. 验证 -----
verify() {
    local dir="$1"; cd "$dir"
    echo ""
    info "验证部署状态..."
    sleep 3

    if $COMPOSE ps 2>/dev/null | grep -q "Up"; then
        log "容器运行中"
    else
        err "容器未正常启动"
        warn "查看日志: cd $dir && $COMPOSE logs"
        return
    fi

    local port=$(grep -E "^PORT=" .env 2>/dev/null | cut -d= -f2)
    port=${port:-8765}

    if curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/login 2>/dev/null | grep -q 200; then
        log "Web 面板响应正常"
    else
        warn "Web 面板暂时无法访问（可能在初始化中）"
    fi

    echo ""
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✅ M+ 量化系统部署完成！${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  访问地址: ${CYAN}http://$(curl -s ifconfig.me 2>/dev/null || echo 'VPS_IP'):$port${NC}"
    echo -e "  本地访问: ${CYAN}http://localhost:$port${NC}"
    echo ""
    echo -e "  默认管理员账号: ${YELLOW}admin${NC}"
    echo -e "  默认管理员密码: ${YELLOW}admin123${NC}"
    echo -e "  ⚠ 首次登录后请立即修改密码！${NC}"
    echo ""
    echo -e "  ${CYAN}常用命令：${NC}"
    echo -e "    查看日志:  cd $dir && $COMPOSE logs -f"
    echo -e "    重启:      cd $dir && $COMPOSE restart"
    echo -e "    停止:      cd $dir && $COMPOSE down"
    echo -e "    升级:      cd $dir && git pull && $COMPOSE up -d --build"
    echo ""
}

# ----- 主流程 -----
main() {
    echo -e "${CYAN}系统检测: $(detect_os)${NC}"
    echo ""
    local dir="${1:-$HOME/m-plus}"
    [ "$dir" = "." ] && dir="$PWD"

    install_docker
    clone_repo "$dir"
    setup_env "$dir"
    build_and_start "$dir"
    verify "$dir"
}

main "$@"
