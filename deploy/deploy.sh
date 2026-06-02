#!/usr/bin/env bash
# ============================================================
# HeAgent 一键部署脚本
# 支持 Docker 和 宿主机 两种部署方式
# 使用: bash deploy/deploy.sh [docker|host]
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="heagent"
DEPLOY_MODE="${1:-docker}"  # 默认 Docker 模式

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 前置检查
check_prerequisites() {
    if [ "$DEPLOY_MODE" = "docker" ]; then
        command -v docker >/dev/null 2>&1 || { log_error "Docker 未安装"; exit 1; }
        command -v docker-compose >/dev/null 2>&1 || { log_error "docker-compose 未安装"; exit 1; }
    else
        command -v python3 >/dev/null 2>&1 || { log_error "Python 3 未安装"; exit 1; }
    fi
}

# 检查生产环境配置文件
check_env_file() {
    if [ ! -f "$PROJECT_DIR/.env.production" ]; then
        log_warn ".env.production 不存在，正在从示例创建..."
        cp "$PROJECT_DIR/.env.production.example" "$PROJECT_DIR/.env.production"
        log_error "请编辑 $PROJECT_DIR/.env.production 填入 API Key 后重新运行"
        exit 1
    fi
}

# ========== Docker 部署 ==========
deploy_docker() {
    log_info ">>> 开始 Docker 部署..."

    cd "$PROJECT_DIR"

    # 构建镜像
    log_info "构建 Docker 镜像..."
    docker build -t "$APP_NAME:latest" -f Dockerfile .

    # 拉取最新代码（如果有 git）
    if git rev-parse --git-dir >/dev/null 2>&1; then
        log_info "更新代码到最新版本..."
        git pull origin master
    fi

    # 启动服务
    log_info "启动 ${APP_NAME} 服务..."
    docker-compose up -d

    # 等待启动并检查健康
    log_info "等待服务启动..."
    sleep 3
    if docker ps --filter "name=${APP_NAME}" --format "{{.Status}}" | grep -q "Up"; then
        log_info "✅ ${APP_NAME} 已成功部署并运行！"
        log_info "查看日志: docker-compose logs -f"
        log_info "测试运行: docker-compose run --rm heagent '你好'"
    else
        log_error "❌ 服务启动失败，请检查日志: docker-compose logs"
        exit 1
    fi
}

# ========== 宿主机部署 ==========
deploy_host() {
    log_info ">>> 开始宿主机部署..."

    local VENV_DIR="$PROJECT_DIR/.venv"
    local INSTALL_DIR="/opt/$APP_NAME"

    # 创建安装目录
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$(whoami):$(whoami)" "$INSTALL_DIR"

    # 复制项目文件
    log_info "复制项目文件到 $INSTALL_DIR..."
    cp -r "$PROJECT_DIR/src" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/pyproject.toml" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/.env.production" "$INSTALL_DIR/"
    cp -r "$PROJECT_DIR/deploy" "$INSTALL_DIR/"

    # 创建虚拟环境
    log_info "创建 Python 虚拟环境..."
    python3 -m venv "$INSTALL_DIR/.venv"
    source "$INSTALL_DIR/.venv/bin/activate"
    pip install --no-cache-dir -e "$INSTALL_DIR"

    # 创建 heagent 用户
    if ! id -u heagent >/dev/null 2>&1; then
        log_info "创建 heagent 系统用户..."
        sudo useradd -r -s /sbin/nologin -d "$INSTALL_DIR" heagent
    fi
    sudo chown -R heagent:heagent "$INSTALL_DIR"

    # 安装 systemd 服务
    log_info "安装 systemd 服务..."
    sudo cp "$INSTALL_DIR/deploy/heagent.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable "$APP_NAME"
    sudo systemctl start "$APP_NAME"

    # 检查状态
    sleep 2
    if sudo systemctl is-active --quiet "$APP_NAME"; then
        log_info "✅ ${APP_NAME} 已成功部署并运行！"
        log_info "查看状态: sudo systemctl status $APP_NAME"
        log_info "查看日志: sudo journalctl -u $APP_NAME -f"
    else
        log_error "❌ 服务启动失败，请检查: sudo journalctl -u $APP_NAME -x"
        exit 1
    fi
}

# ========== 主流程 ==========
main() {
    echo "========================================"
    echo "  HeAgent 部署脚本"
    echo "  模式: $DEPLOY_MODE"
    echo "========================================"

    check_prerequisites
    check_env_file

    case "$DEPLOY_MODE" in
        docker)
            deploy_docker
            ;;
        host)
            deploy_host
            ;;
        *)
            log_error "未知部署模式: $DEPLOY_MODE (支持: docker / host)"
            exit 1
            ;;
    esac

    log_info "部署完成！🎉"
}

main "$@"
