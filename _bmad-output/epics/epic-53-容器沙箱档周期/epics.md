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
epic 期一交付后由用户裁定是否开期二——**2026-11-03 用户裁定开启期二**：53-4（审批降级接入）
/ 53-5（MCP stdio 进容器）见下表。

**立场口径**：容器档是 OS 级强隔离兜底，**不是绝对边界**（宿主内核 / Docker daemon 自身
逃逸风险仍在）；弱后端一律不得审批降级（NFR-2 既有锁）。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 交付物 | 验收要点 |
|---|---|---|---|---|---|
| 53-1 | DockerRunner 与注入接线 | 无 | done（2026-10-24 用户 walkthrough 验收通过；判据 11 绿 + 变异体 6/6，真实 daemon 链路由 53-2 integration 实证） | `tools/sandbox/docker.py` `DockerRunner` 实现 `CommandRunner` Protocol（`tier=CONTAINER`）；`configure_command_runner` 接线；不可用降级 Passthrough + **显性留痕**（对齐「显性失败」仓库原则） | 判据用替身（fake runner / 假 `docker` CLI 探测），常规测试**不调用真实 daemon**；真实链路标 `integration` 标记；变异体验证精确变红 |
| 53-2 | 镜像、配置面与网络档 | 53-1 | done（2026-10-24 用户 walkthrough 验收通过；单测 102 绿 + integration 3/3，全链判据由 53-3 判据 11 闭合） | 镜像构建文件 + `python:3.11-slim` 基座 + 项目依赖；镜像 pin digest；网络档开关挂 `Settings`（`none` 默认 / bridge 显式开启，失败显性报错） | 无 daemon 时全部用例可跑（替身）；`integration` 用例覆盖真实构建/运行；`Dockerfile` 依赖层与 CI 对齐口径记录在 story 内 |
| 53-3 | 文档、契约与质量门 | 53-1, 53-2 | done（2026-10-24 用户 walkthrough 验收通过；全量门 3740 绿，两笔既有失守闭合；docker.io 直连验证残余转 D53-3） | 判据 11（SandboxDecision 全链，53-2 挂账闭合）；`docs/frame.md` 8 处 + AGENTS.md 3 处同步（立场行逐行复核不改、不扩大宣称）；台账契约对齐（恒零→计数真实性 + epic-53 状态总览 + 四处计数刷新）+ 端口顺延陈旧用例对齐现行契约；skills.py ruff 漂移 chore | 全量 `pytest`（跳过 integration/benchmark）+ `ruff` + `mypy` 全绿；`tests/test_architecture_contracts.py` 零改动 |
| 53-4 | 审批降级接入 PolicyEngine（期二 D53-2） | 53-1 | done（2026-11-03 判据 12 绿 + 变异体 5/5 精确变红；待用户 walkthrough 验收） | `PolicyEngine._container_relaxes_approval` + `PolicyVerdict.approval_relaxed` + `EngineContainer` 惰性 provider 接线；`tests/test_sandbox_approval_relax.py`；`scripts/mutation/mutate_approval_relax.py`；frame.md 2 处 + docs/sandbox.md 1 处同步 | 四条全成立才放松（真进沙箱 / 容器档 / 后端可用 / 读取未抛错）；弱后端与降级 Passthrough 仍要求审批（NFR-2）；放松不绕过沙箱授权；显性 WARNING 留痕 |
| 53-5 | MCP stdio 进容器（期二 D53-1） | 53-1 | done（2026-11-03 判据 11 条全绿 + 变异体 6/6 精确变红 + 六门 all passed；待用户 walkthrough 验收） | `tools/mcp/stdio_sandbox.py`（`StdioSandboxSpec` / `build_run_argv` / `stdio_params` + 显性降级）；`client.default_transport_opener(stdio_sandbox=)`；`MCPClientManager(stdio_sandbox=)`；`cli/console.py::_stdio_sandbox_spec`；`docker_available()` 公共包装；`tests/test_mcp_stdio_sandbox.py`；`scripts/mutation/mutate_mcp_stdio_sandbox.py` | `docker run -i --rm` 长命双向管道（不复用 `CommandRunner`）；硬化旗标与 DockerRunner 同源；env 只透传声明键（值不进 argv）；后端不可用 ⇒ 显性降级 + 每次 WARNING；镜像内缺二进制显性失败 |

## 实施约束

1. 交付顺序 `53-1 → 53-2 → 53-3`；53-1 判据用替身，真实 daemon 链路一律 `integration` 标记（常规 `pytest` 跳过）。
2. **D1–D4 决策冻结在 `brief.md`**，任一变更须经用户裁定并回写 brief。
3. `DockerRunner` 形状沿用既有短命命令捕获（`sh -c` 收尾）——**不得**用该缝承载长命双向管道（那是期二 D53-1 的新缝，勿提前占位）。
4. 弱后端不得审批降级（NFR-2）；容器档文档表述不得扩大为「绝对边界」。
5. 降级 Passthrough 不得静默——显性留痕（WARNING 或事件）。
6. 新文件放 `tools/sandbox/` 内，不新增跨包依赖；若依赖面变化同步 `tests/test_architecture_contracts.py`。
7. 每个 story 的验证命令是规划口径，执行后登记实测结果；引用不存在的文件按实测更正。
