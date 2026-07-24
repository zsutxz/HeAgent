#!/usr/bin/env bash
# ============================================================
# HeAgent 一键部署脚本
# 支持 Docker 和 宿主机 两种部署方式
# 使用: bash deploy/deploy.sh [docker|host]
#
# 注意: HeAgent 是 CLI 工具，不是常驻服务。
#   Docker 模式构建镜像后通过 `docker compose run --rm` 使用。
#   Host 模式通过 pip install + cron 调度（如需要定时任务）。
#   systemd 服务单元已移除——交互式 CLI 不适合作为无人值守守护进程。
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

    # 拉取最新代码（先拉取，再构建——确保构建的是最新代码）
    if git rev-parse --git-dir >/dev/null 2>&1; then
        log_info "更新代码到最新版本..."
        git pull origin master
    fi

    # 构建镜像
    log_info "构建 Docker 镜像..."
    docker compose build

    # 验证镜像
    log_info "验证镜像..."
    docker compose run --rm "$APP_NAME" --help

    log_info "✅ ${APP_NAME} Docker 镜像已构建完成！"
    log_info ""
    log_info "使用方式:"
    log_info "  单次执行:  docker compose run --rm heagent '你的问题'"
    log_info "  交互模式:  docker compose run --rm heagent"
    log_info "  定时任务:  使用宿主 cron 调用 docker compose run --rm heagent 'prompt'"
    log_info "  查看日志:  docker compose logs"
}

# ========== 宿主机部署 ==========
deploy_host() {
    log_info ">>> 开始宿主机部署..."

    cd "$PROJECT_DIR"

    # 安装 HeAgent（可编辑模式）
    log_info "安装 HeAgent..."
    pip install -e "."

    # 验证安装
    log_info "验证安装..."
    heagent --help

    log_info "✅ ${APP_NAME} 已安装完成！"
    log_info ""
    log_info "使用方式:"
    log_info "  单次执行:  heagent '你的问题'"
    log_info "  交互模式:  heagent"
    log_info ""
    log_info "如需定时任务，使用系统 cron:"
    log_info "  crontab -e"
    log_info "  0 9 * * * cd $(pwd) && heagent 'fetch_ai_news'"
    log_info ""
    log_info "注意: HeAgent 内置 cron 调度器（heagent 交互模式内 / cron_add 工具），"
    log_info "      但该调度器在进程退出后不持久；"
    log_info "      如需生产级定时任务，建议外层系统 cron 或 systemd timer 触发单次执行。"
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
