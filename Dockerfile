# ============================================================
# HeAgent 生产 Docker 镜像
# 多阶段构建: build → run
#
# 构建:
#   # 不锁定 base image（CI 默认）
#   docker build -t heagent .
#
#   # 锁定 base image digest（生产推荐，先 docker pull 取最新 digest）
#   docker build -t heagent \
#     --build-arg BASE_DIGEST=@sha256:abc123... \
#     --build-arg RUNNER_DIGEST=@sha256:abc123... .
# ============================================================

# digest 锁定通过 build arg 控制，默认不锁（从 registry 拉最新）
ARG BASE_DIGEST=
ARG RUNNER_DIGEST=

# ---- Stage 1: Build ----
FROM python:3.11-slim${BASE_DIGEST} AS builder

WORKDIR /build

# 安装构建依赖（mcp 等依赖均为纯 Python wheel，gcc 为兜底）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# 构建 wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# ---- Stage 2: Run ----
FROM python:3.11-slim${RUNNER_DIGEST} AS runner

WORKDIR /app

# 安装运行时依赖（最小化攻击面）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制 wheel
COPY --from=builder /build/dist/*.whl /tmp/

# 安装 HeAgent 及其依赖
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm /tmp/*.whl

# 创建运行时数据目录
RUN mkdir -p /data/heagent

# 创建非 root 用户（-s /sbin/nologin 防交互式 login，不影响 ENTRYPOINT exec）
RUN groupadd -r heagent && \
    useradd -r -g heagent -d /app -s /sbin/nologin heagent && \
    chown -R heagent:heagent /app /data/heagent

# 使用非 root 用户运行
USER heagent

# 健康检查（HeAgent 为 CLI 库，无 HTTP 端点；用 import 检测 Python 进程存活性）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import heagent; print('ok')" || exit 1

# 默认命令：交互模式（可被 docker run 覆盖）
ENTRYPOINT ["python", "-m", "heagent"]
CMD []
