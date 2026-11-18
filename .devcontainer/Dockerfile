# HeAgent 开发容器镜像。
#
# 分工约定（改这里前先读）：
# - **镜像**只装「与仓库源码无关」的东西：Python 运行时、系统工具、以及 pip 自身的环境设置。
#   这样镜像层可以跨分支复用，不会因为改一行源码而整层重建。
# - **项目依赖**由 devcontainer.json 的 postCreateCommand 以 editable 方式装到挂载的源码上
#   （`pip install -e ".[dev,gui,http]"`）：extras 的版本区间只有 `pyproject.toml` 一个真源，
#   在这里重复列举必然漂移。
#
# 基础镜像的 Python 次版本必须与 `pyproject.toml` 的 `requires-python` 下界一致
# （当前 >=3.11）；不一致会被 `tests/test_devcontainer_contract.py` 拦下。
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# pip 行为固化：不检查新版本（会打断构建输出）、不缓存 wheel（镜像体积）、不写 .pyc（9p/挂载上噪声大）。
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 系统工具：
# - ripgrep：手工排查大仓库时比 `grep -r` 快一个量级（工具实现本身不依赖它）；
# - jq：读 `.heagent/runs/*.json` 与 WS 帧排障时用得上；
# - less / procps：进程与日志分页（镜像自带，此处显式化以免上游基础镜像瘦身时静默消失）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep jq less procps \
    && rm -rf /var/lib/apt/lists/*

# 容器内默认工作目录 = 源码挂载点（devcontainer 的 workspaceFolder）。
WORKDIR /workspaces/HeAgent
