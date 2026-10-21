---
stepsCompleted: []
status: draft
inputDocuments:
  - docs/frame.md
  - _bmad-output/epics/epic-53-容器沙箱档周期/brief.md
  - _bmad-output/epics/epic-53-容器沙箱档周期/deferred-work.md
---

# HeAgent - Epic Breakdown（Epic 53：容器沙箱档）

把 `SandboxTier.CONTAINER` 从预留枚举落地为实现后端：shell 工具执行收进 Docker 容器
（OS 级强隔离兜底），`--network=none` 默认 + 显式配置开启 bridge，后端不可用优雅降级
Passthrough 且留痕。期二（MCP stdio 进容器 + 审批降级接入）挂 `deferred-work.md`，本
epic 期一交付后由用户裁定是否开期二。

**立场口径**：容器档是 OS 级强隔离兜底，**不是绝对边界**（宿主内核 / Docker daemon 自身
逃逸风险仍在）；弱后端一律不得审批降级（NFR-2 既有锁）。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 交付物 | 验收要点 |
|---|---|---|---|---|---|
| 53-1 | DockerRunner 与注入接线 | 无 | review（2026-10-21 判据 11 绿 + 变异体 6/6 精确变红；真实 daemon 链路验证挂 53-2） | `tools/sandbox/docker.py` `DockerRunner` 实现 `CommandRunner` Protocol（`tier=CONTAINER`）；`configure_command_runner` 接线；不可用降级 Passthrough + **显性留痕**（对齐「显性失败」仓库原则） | 判据用替身（fake runner / 假 `docker` CLI 探测），常规测试**不调用真实 daemon**；真实链路标 `integration` 标记；变异体验证精确变红 |
| 53-2 | 镜像、配置面与网络档 | 53-1 | review（2026-10-21 单测 102 绿 + 真实 daemon integration 3/3；SandboxDecision 全链判据挂 53-3） | 镜像构建文件 + `python:3.11-slim` 基座 + 项目依赖；镜像 pin digest；网络档开关挂 `Settings`（`none` 默认 / bridge 显式开启，失败显性报错） | 无 daemon 时全部用例可跑（替身）；`integration` 用例覆盖真实构建/运行；`Dockerfile` 依赖层与 CI 对齐口径记录在 story 内 |
| 53-3 | 文档、契约与质量门 | 53-1, 53-2 | planned | `docs/frame.md` 五 container 行与 §4.x sandbox 小节同步；AGENTS.md 安全声明同步；`tests/test_architecture_contracts.py` 核对（新增文件不新增跨包依赖则零改动）；全量质量门亲跑留痕 | 全量 `pytest`（跳过 integration/benchmark）+ `ruff` + `mypy` 全绿；frame.md 约 12 处「须 OS 级沙箱兜底」表述按 container 档实际覆盖面逐行复核后修订，**不得**扩大宣称 |

## 实施约束

1. 交付顺序 `53-1 → 53-2 → 53-3`；53-1 判据用替身，真实 daemon 链路一律 `integration` 标记（常规 `pytest` 跳过）。
2. **D1–D4 决策冻结在 `brief.md`**，任一变更须经用户裁定并回写 brief。
3. `DockerRunner` 形状沿用既有短命命令捕获（`sh -c` 收尾）——**不得**用该缝承载长命双向管道（那是期二 D53-1 的新缝，勿提前占位）。
4. 弱后端不得审批降级（NFR-2）；容器档文档表述不得扩大为「绝对边界」。
5. 降级 Passthrough 不得静默——显性留痕（WARNING 或事件）。
6. 新文件放 `tools/sandbox/` 内，不新增跨包依赖；若依赖面变化同步 `tests/test_architecture_contracts.py`。
7. 每个 story 的验证命令是规划口径，执行后登记实测结果；引用不存在的文件按实测更正。
