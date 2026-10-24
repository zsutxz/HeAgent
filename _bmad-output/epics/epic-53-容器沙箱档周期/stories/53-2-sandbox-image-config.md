# Story 53-2 · 镜像、配置面与网络档

状态：**done**（2026-10-21 单测 102 绿 + **真实 daemon integration 3/3**；SandboxDecision 全链判据已由 53-3 判据 11 闭合。2026-10-24 用户 walkthrough 验收通过）。

## 交付物

- `docker/sandbox/Dockerfile`：`heagent-sandbox:3.11` 镜像。基座 `python:3.11-slim`
  **pin digest** `sha256:e88e9763…`（2026-10-21 查证，经 daocloud 镜像源；`ARG BASE` 支持换源重建，
  manifest 字节一致）。工具链立场：只装 `git + ca-certificates`——git 为 shell 工作流高频依赖；
  容器默认无网，pip 装包显性失败是 D2 的立场而非缺陷。
- `config/__init__.py`：新字段 `sandbox_docker_image`（默认 `heagent-sandbox:3.11`，env
  `SANDBOX_DOCKER_IMAGE`）；`sandbox_backend` / `sandbox_network` 注释与 `.env.example` 同步
  （`test_every_settings_field_is_documented_in_env_example` 判据钉住）。
- `cli/console.py`：`--sandbox` Choice 增 `docker`。
- `engine/container.py`：resolver docker 分支吃 Settings（镜像 + 网络档：`SANDBOX_NETWORK=True`
  才 bridge，D2）。

## 验收证据（2026-10-21 亲跑）

- 单测：`tests/test_sandbox_docker.py` 11/11（判据 10 扩为 Settings 传播 + 网络档双态）+
  `tests/test_config.py` 全绿（env-example 判据）。
- **integration 3/3**（`tests/test_sandbox_docker_integration.py`，真实 daemon）：
  ①真实执行 + workspace 挂载（`cat /workspace/hello.txt` + `git --version`）；
  ②网络隔离实证（默认 none 档下容器内出站连接显性失败）；
  ③env 隔离实证（宿主 sentinel 变量在容器内不可见）。
- 静态：ruff check/format、mypy（3 文件）全绿。
- 镜像实建：`heagent-sandbox:3.11`（331MB）已在本机构建并入库 local store。

## 残余（如实标注）

- SandboxDecision 的 docker 路径（`EngineContainer.default` 全链）无单测——resolver 分支有判据
  （test 10），default 装配链判据挂 53-3 质量门。
- digest 经镜像源查证（daocloud 与 docker.io manifest 字节一致），docker.io 直连验证留待 53-3。
