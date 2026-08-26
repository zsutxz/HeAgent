---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - 本会话范围评估（hermes 式沙箱后端抽象 P1/P2/P3 分解，2026-08-26）
  - CLAUDE.md（安全声明 / 已知缺口 / 硬约束）
  - docs/frame.md（架构权威：模块 DAG、4.12 运行时引擎、五 已知缺口）
  - 源码勘察（tools/sandbox.py、engine/executor.py、engine/policy.py、tools/builtins 清单）
---

# HeAgent - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for HeAgent, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: 沙箱会话目录约定——`FirejailBackend` / `WinJobBackend` 支持 per-task 持久 workspace 目录：Firejail `--private` 指向 session 目录实现 OS 级文件系统隔离；WinJob 侧采用同一目录约定（无真实文件系统隔离，仅为会话工作区约定）。
FR-2: PolicyEngine 沙箱后端分级——引入后端强度分级（`passthrough < job < firejail < container`），裁决与执行路径可感知当前后端强度；`container` 档位仅预留枚举（暂无实现后端）；任何弱于 container 的后端不得触发审批降级。
FR-3: 声明式 env 豁免——`scrub_sensitive_env` 配套 allowlist 配置入口（`Settings` 字段 + `.env` 覆盖），命中 allowlist 的环境变量不再被剥离即传入 shell 子进程。
FR-4: SandboxSession 会话生命周期——per-task 持久 workspace + cwd 跨命令保持 + teardown 清理；将 `ToolExecutor.execute_in_sandbox` 从无状态逐命令包装重构为会话作用域执行。
FR-5: （deferred）execute_code RPC 沙箱工具——LLM 生成的 Python 在沙箱子进程内执行，经白名单 RPC 工具桥访问受限工具集。

### NonFunctional Requirements

NFR-1: 非真边界立场——所有新增沙箱能力在 `CLAUDE.md` 已知缺口与 `docs/frame.md` 中明示为 defense-in-depth；Windows（WinJob）路径明确标注零文件系统/网络隔离，不制造「已有沙箱边界」的错觉。
NFR-2: 审批不可因弱后端跳过——审批降级逻辑仅对 container 级后端开放（当前不存在实现），弱后端（passthrough/job/firejail）一律维持原审批要求。
NFR-3: 跨平台可用性——Windows 主力平台（WinJob + Passthrough）全路径可用；Linux firejail 路径保持既有优雅降级惯例（firejail 不可用 → warn + Passthrough）。
NFR-4: 项目规范——跨模块数据一律 Pydantic 模型；库代码全异步无同步 I/O；模块依赖 DAG 不破坏；新逻辑配 pytest 测试（意图级断言）。

### Additional Requirements

- 工具执行链固定顺序 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler 不可破坏；SandboxSession 重构不得改变该链路形态。
- 模块依赖方向不变：`engine/` 依赖 `types`/`exceptions`/`tools.safety`；沙箱后端注入仍经 `EngineContainer`（`command_runner=`），`AgentLoop` 零改动。
- 现状锚点（增量基线）：`tools/sandbox.py` 已有 `FirejailBackend`（profile→args 映射、`--private`、`os.killpg`）与 `WinJobBackend`（Job Objects、`KILL_ON_JOB_CLOSE`）；`engine/executor.py` `SANDBOX_REQUIRED` 为无状态路径；`scrub_sensitive_env` 已存在（Epic 36-39）。
- 既有配置入口 `SANDBOX_BACKEND` env / `--sandbox` CLI 保持向后兼容，只扩展不破坏。
- 文档同步义务：`docs/frame.md`（4.4/4.12/五）与 `CLAUDE.md` 已知缺口随代码交付同步更新（活的架构权威惯例）。
- 后续升级路径预留：Linux bubblewrap/nsjail、Windows AppContainer 将来可作为新 Backend 落入 container/更强档位，分级框架须使其免重构接入。

### UX Design Requirements

（无——本周期纯后端，无 UI 交付物。）

### FR Coverage Map

FR-1: Epic 40 — 会话目录约定（Firejail `--private` / WinJob 目录约定）
FR-2: Epic 40 — PolicyEngine 后端强度分级 + container 档预留
FR-3: Epic 40 — `scrub_sensitive_env` 声明式 allowlist
FR-4: Epic 40 — SandboxSession 生命周期重构
FR-5: （deferred，未映射）execute_code RPC 沙箱工具——未来独立周期，本周期不建 story

## Epic List

### Epic 40: 沙箱会话化执行（hermes 式后端抽象）

Agent 的 shell 命令执行从「无状态逐命令透传」升级为「per-task 会话化沙箱执行」——每个任务获得持久 workspace、cwd 跨命令保持、teardown 清理；策略层可感知沙箱后端强度（`passthrough < job < firejail < container`，container 档预留）且弱后端不降审批；敏感环境变量支持声明式豁免。框架使用者在 Windows/Linux 均获得会话级沙箱工作流，并明确知晓其 defense-in-depth 性质（非真边界立场写入文档）。

**FRs covered:** FR-1, FR-2, FR-3, FR-4

内部 story 顺序：P1（FR-1/2/3，纯增量）→ P2（FR-4，动 `execute_in_sandbox` 主干需完整回归）。epic 内 story 间无前向依赖，Epic 40 自身独立成立（不含 FR-5 也完整）。

## Epic 40: 沙箱会话化执行（hermes 式后端抽象）

Agent 的 shell 命令执行从「无状态逐命令透传」升级为「per-task 会话化沙箱执行」——每个任务获得持久 workspace、cwd 跨命令保持、teardown 清理；策略层可感知沙箱后端强度（`passthrough < job < firejail < container`，container 档预留）且弱后端不降审批；敏感环境变量支持声明式豁免。框架使用者在 Windows/Linux 均获得会话级沙箱工作流，并明确知晓其 defense-in-depth 性质（非真边界立场写入文档）。

**FRs covered:** FR-1, FR-2, FR-3, FR-4

### Story 40.1: 沙箱会话目录管理（FR-1）

As a 框架使用者,
I want 每个任务（run）拥有按命名规范创建/定位的持久沙箱 workspace 目录——Firejail 将其作为 `--private` 根、WinJob 将其作为命令 cwd,
So that 沙箱内命令的读写落在任务专属工作区，任务间互不污染。

**Acceptance Criteria:**

**Given** 任意 run_id，**When** 请求其沙箱 workspace，**Then** 返回统一规范目录（如 `.heagent/sandboxes/<run_id>/`，幂等创建），不依赖执行器状态
**And** `FirejailBackend` + 会话目录执行命令时 `--private=<该目录>` 生效（复用既有 `workspace_root` 映射，不新增参数路径）
**And** Windows `WinJobBackend` + 会话目录执行命令时子进程 cwd 为该目录（目录约定，**无文件系统隔离**——代码注释与文档明示）
**And** 未启用会话目录时行为与现状完全一致（向后兼容）
**And** firejail/WinJob 不可用时维持既有 warn + Passthrough 降级，不因目录管理引入新失败路径

### Story 40.2: 沙箱后端强度分级（FR-2）

As a 框架使用者,
I want 策略与执行路径可感知沙箱后端强度（`passthrough < job < firejail < container`，Pydantic 模型）,
So that 裁决基于真实隔离能力，未来 bwrap/nsjail/AppContainer 接入免重构。

**Acceptance Criteria:**

**Given** 分级模型，**When** 后端实例化，**Then** 各后端正确声明档位：Passthrough→`passthrough`、WinJob→`job`、Firejail→`firejail`；`container` 档存在于枚举、无实现后端（预留）
**When** `SANDBOX_REQUIRED` 执行路径查询当前后端强度，**Then** 执行上下文（如 `RunContext.metadata` 或 verdict）可获取档位（Pydantic，无裸值）
**Given** 弱于 `container` 的任意后端，**When** 触发审批语义裁决，**Then** 审批要求与现状一致（**测试锁定**：弱后端不得触发审批降级）
**And** 分级语义与升级路径写入 `docs/frame.md` 4.12

### Story 40.3: 声明式环境变量豁免（FR-3）

As a 框架使用者,
I want 经 allowlist 配置声明豁免 `scrub_sensitive_env` 剥离的环境变量,
So that 受信任务需要的凭证（如 `GITHUB_TOKEN`）能进入 shell 子进程，其余敏感变量仍被剥离。

**Acceptance Criteria:**

**Given** allowlist 含 `GITHUB_TOKEN`，**When** spawn shell 子进程，**Then** `GITHUB_TOKEN` 传入，其余命中剥离规则的变量（`*_API_KEY` 等）仍被剥离
**Given** allowlist 未配置/为空，**When** spawn，**Then** 行为与现状逐字节一致（默认全剥离，向后兼容）
**Given** `Settings` 字段 + `.env` 覆盖入口，**When** 用户声明豁免，**Then** 无需改代码（配置文档同步更新）
**And** 豁免仅作用于 env 剥离，不影响 `path_safety` 凭证文件读写 deny 与 `SafetyGuard` 凭证路径拦截

### Story 40.4: SandboxSession 会话生命周期（FR-4）

As a 框架使用者,
I want 同一 run 的连续 shell 命令共享 SandboxSession——同一 workspace、cwd 跨命令保持、run 结束 teardown,
So that 多步操作（写文件→编译→运行）自然衔接，无需逐命令重建状态。

**Acceptance Criteria:**

**Given** 同一 run 的先后两条命令，**When** 第二条执行，**Then** 复用同一会话（同一 workspace 目录；Firejail 下同一 `--private` 视图）
**Given** 第一条 `cd sub && touch a`，**When** 第二条 `pwd && ls`，**Then** cwd 保持在 `sub` 且 `a` 可见（跨命令状态保持）
**Given** run 结束（正常/异常/取消），**When** teardown，**Then** 会话目录按配置清理（保留/删除），无孤儿进程（复用 killpg/KILL_ON_JOB_CLOSE 既有机制）
**Given** `SANDBOX_REQUIRED` 但未注入 runner，**When** 执行，**Then** 既有 fail-safe 报错语义不变
**And** 工具执行链 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler` 形态不变（既有 sandbox 测试全绿 + 新增会话语义测试）
**And** `CLAUDE.md` 已知缺口与 `frame.md` 4.4/4.12 同步更新（NFR-1 非真边界立场）
