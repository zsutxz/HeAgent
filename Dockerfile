# ============================================================
# HeAgent 生产 Docker 镜像
# 多阶段构建: build → run
# ============================================================

# ---- Stage 1: Build ----
# digest 锁定日期: 2026-07-22（需 Docker 环境运行 `docker pull python:3.11-slim` 获取最新 digest 后更新）
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml README.md ./
COPY src/ ./src/

# 构建 wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# ---- Stage 2: Run ----
FROM python:3.11-slim AS runner

WORKDIR /app

# 安装运行时依赖（最小化攻击面）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制 wheel
COPY --from=builder /build/dist/*.whl /tmp/

# 安装 HeAgent 及其依赖
RUN pip install --no-cache-dir /tmp/*.whl

# 创建运行时数据目录
RUN mkdir -p /data/heagent && \
    chmod 755 /data/heagent

# 创建非 root 用户
RUN groupadd -r heagent && \
    useradd -r -g heagent -d /app -s /sbin/nologin heagent && \
    chown -R heagent:heagent /app /data/heagent

# 使用非 root 用户运行
USER heagent

# 健康检查（HeAgent 为 CLI 库，无 HTTP 端点；用 import 检测进程存活性）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import heagent; print('ok')" || exit 1

# 默认命令：交互模式（可被 docker run 覆盖）
ENTRYPOINT ["python", "-m", "heagent"]
CMD []
