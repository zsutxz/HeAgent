---
title: 'Story 65.6 提供开发环境配置'
type: feature
ticket: 6
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - '.devcontainer/Dockerfile'
  - '.devcontainer/devcontainer.json'
  - 'README.md'
  - 'tests/test_devcontainer_contract.py'
---

## Intent

**Problem:** 票面要求「devcontainer.json 或 Dockerfile.dev 一键开发环境就绪，包含全部必需依赖与
预配置检查工具」。勘差结论：仓库里只有**产物镜像**的 `Dockerfile`（运行 `heagent` 服务/CLI），
没有任何开发环境载体——新人 clone 后要自己拼 Python 版本、三套 extras、pre-commit 钩子与端口转发。
而 `mypy src` 需要 `gui`（textual）与 `http`（starlette/uvicorn）两套 extras 才对，
`dev` 里没有它们 ⇒ 只装 `[dev]` 的环境连 mypy 门都跑不通。

**Approach：** 新增 `.devcontainer/`，把「镜像层」与「项目依赖」刻意分开：

- `Dockerfile`：基础镜像 `mcr.microsoft.com/devcontainers/python:1-3.11-bookworm`（X.Y 必须等于
  `requires-python` 下界）+ pip 环境固化 + 少量系统工具（ripgrep / jq / less / procps）。
  **不在镜像里列举 extras**——版本区间的唯一真源是 `pyproject.toml`，镜像里再抄一份必然漂移。
- `devcontainer.json`：`postCreateCommand = pip install -e ".[dev,gui,http]" && pre-commit install`；
  `forwardPorts` 跟随三条 listener 默认端口；VSCode 扩展 ruff/mypy/pytest 预配。

**Verify 落成判据**（`tests/test_devcontainer_contract.py`，4 例）：

1. `build.dockerfile` 指向的文件存在；
2. postCreate 的 extras 全部在 `pyproject.toml` 里声明、且必含 `dev`/`gui`/`http`，并含 `pre-commit install`；
3. `forwardPorts` 集合 == `{Settings().http_port, ws_port, ws_external_port}`（改默认端口忘改转发即红）；
4. Dockerfile 基础镜像的 Python X.Y == `requires-python` 下界。

## Verify 实测

- `pytest tests/test_devcontainer_contract.py -q` → 4 passed。
- **未实测`devcontainer up` 墙钟**：本开发容器内无 docker daemon（`docker info` 不可用），构建耗时按
  步骤估算（基础镜像拉取 + apt + `pip install -e ".[dev,gui,http]"`，冷启 2–3 分钟、镜像层缓存后 <1 分钟），
  README 里如实标注为「约」值而非实测。这一条属环境限制，不是遗漏。

## Boundaries

- 不装 docker-in-docker：沙箱后端 docker 面向宿主 daemon（本仓常规用法是宿主 Windows/WSL2 侧），
  在开发容器里起 dind 会让「容器里的容器」与 9p 挂载叠加成新的排障面。
- 不在 Dockerfile 里复制 extras 清单（单一真源 = `pyproject.toml`）。
- 不动产物 `Dockerfile`（那是部署面，归 `deploy/README.md`）。
