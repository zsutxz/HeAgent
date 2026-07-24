# ============================================================
# HeAgent 生产 Docker 镜像
# 多阶段构建: build → run
#
# 构建:
#   docker build -t heagent .
#   docker build -t heagent --build-arg BASE_DIGEST=@sha256:abc... --build-arg VERSION=0.3.0
# ============================================================

ARG BASE_DIGEST=
ARG RUNNER_DIGEST=
ARG VERSION=unknown

# ---- Stage 1: Build ----
FROM python:3.11-slim${BASE_DIGEST} AS builder

WORKDIR /build

# 复制项目文件
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# 构建 wheel（全部依赖为纯 Python，无需 gcc）
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# ---- Stage 2: Run ----
FROM python:3.11-slim${RUNNER_DIGEST} AS runner

WORKDIR /app

# OCI 标准镜像标签（Docker Hub / GHCR 页面渲染用）
LABEL org.opencontainers.image.source="https://github.com/zsutxz/HeAgent"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.description="A self-improving AI Agent core framework"
LABEL org.opencontainers.image.licenses="MIT"

# 从 builder 复制 wheel
COPY --from=builder /build/dist/*.whl /tmp/

# 安装 HeAgent 及其依赖
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm /tmp/*.whl

# 创建运行时数据目录
RUN mkdir -p /data/heagent

# 创建非 root 用户
RUN groupadd -r heagent && \
    useradd -r -g heagent -d /app -s /sbin/nologin heagent && \
    chown -R heagent:heagent /app /data/heagent

USER heagent

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import heagent; print('ok')" || exit 1

ENTRYPOINT ["heagent"]
CMD []
