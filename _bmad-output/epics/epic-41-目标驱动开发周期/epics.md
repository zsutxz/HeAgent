---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - spec-goal-command（spec-goal-command/：SPEC.md 七能力契约 + goal-workflow-contract.md 状态文件契约，2026-08-29 蒸馏，Epic 41 归档源）
  - 用户多轮澄清（2026-08-28~29 会话）：载体/形态/范围拍板 + 「具体开发流程通过 skill 实现、goal 不写成 Python 文件」+ 「本 epic 重点是 /goal 启动特定 skill、通过 skill 执行工作流」
  - CLAUDE.md（硬约束 / 测试惯例 / 已知缺口）
  - docs/frame.md（架构权威）
  - 源码勘察（cli.py slash/cron 接线、agent/sub.py、context/window_reset.py、slash.py、engine/persist.py）
---

# HeAgent - Epic Breakdown

> Canonical goal-command contract: [`spec-goal-command/SPEC.md`](spec-goal-command/SPEC.md) and [`spec-goal-command/goal-workflow-contract.md`](spec-goal-command/goal-workflow-contract.md). These documents are archived with Epic 41 and are the maintained source for the goal workflow requirements.

## Overview

This document provides the complete epic and story breakdown for HeAgent, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: `/goal` 启动 goal skill 并执行单步工作流——skill 正文确定性注入（路径直读 `.heagent/skills/goal/SKILL.md`，不走相似度匹配）；每次任务（一次 planning / 一条 story）开一个**全新 SubAgent 会话**（fresh context + 新 LLM 连接，`window_reset` 武装 `settings.window_reset_threshold` 实现 token 阈值清窗续跑）；子命令 `new/next/status/reset`；GOAL.md 边界扫描（status 行 + checkbox 完成度）违约显性报错。
FR-2: `/goal run` 连续推进 story 直至 done；触 max rounds（常量默认 10）显性报错。
FR-3: SubAgent 增 `metadata` 参数——goal 会话的 run 快照携带 `goal_id`/`goal_kind`，可在 engine 观测体系中按 goal 过滤。
FR-4: `/goal auto` cron 无人值守——`JobStore` 注册定时推进（prompt 前缀 `goal-advance <goal_id>` 约定），`_run_job` 闭包前缀路由分流到 goal 推进路径；done/blocked 后自动注销；进程内并发锁；CLI 重启经 jobs.json 续跑。

### NonFunctional Requirements

NFR-1: 分层铁律（用户多轮拍板）——**工作流方法论只存在于 skill 文件**（人可直接编辑定制）；禁止 `goal.py` 独立模块、Pydantic GoalState、迁移校验表、runs.jsonl 审计文件；机制代码全部落 `cli.py`（增量约 130 行内，仿 `_dream_runner`/`_run_job` 闭包先例）。
NFR-2: 显性失败——skill 缺失（报错附创建指引）、状态文件缺失/无合法 status 行、无活跃 goal、run 触顶，一律报错回显不静默。
NFR-3: 无人值守零提权——goal 会话照走 PolicyEngine 审批，按既有 fail-safe 语义（拒绝 → story blocked → job 注销回显）。
NFR-4: 向后兼容——`sub.py` metadata 默认 None 行为不变；非 goal 前缀的 cron job 路径与现状逐字节一致（回归锁定）。
NFR-5: 项目规范——测试遵守仓库惯例（内联 StubProvider 脚本化 tool_calls、`monkeypatch.chdir(tmp_path)`、每测试 `reset_settings()`）；中文注释；`docs/frame.md` 活文档同步。

### Additional Requirements

- **本 epic 主线**：`/goal` 是启动器，skill 是执行者——命令只负责「注入 skill + 开新会话 + 扫边界」，工作流（拆 story / 逐 story 实现+验收 / 状态落盘纪律）全部由 skill 契约驱动；改工作流 = 改 skill 文本，零代码变更。
- engine 经 `loop.engine` 公开属性获取，不扩 `_build_slash_registry` 签名；子命令参数缺失打印用法不做 `input()` 追问；会话期间 Ctrl+C 打断兜底回显「状态在盘可续跑」。
- goal 目录约定：`.heagent/goals/<uuid4().hex[:8]>/`（`current` 指针文件存 goal_id；`goal.txt` 存原始描述——GOAL.md 缺失时重跑 planning 的恢复路径）。
- `.heagent/` 为 gitignore 运行时目录：skill 文件属本地运行件，skill 缺失报错的创建指引即分发通道；是否随包分发示例 skill 为后续独立事项（不占本 epic）。
- 通用化 defer：未来可把「斜杠命令 → skill 工作流循环」泛化为任意 skill 启动器；本 epic 硬绑定 goal skill 路径（MVP 简约）。
- 非目标（有意不做）：独立 review run（验收内嵌 story 规程）；代码级状态机校验；goal 会话流式输出与 REPL 内打断（`SubAgent.run_stream` defer）；`goal_update` 类型化工具；`file_write` 原子化与跨进程锁；`SubAgentResult` usage 字段。

### UX Design Requirements

交互 CLI 子命令（保留字封闭集）：

| 输入 | 行为 |
|------|------|
| `/goal <描述>` / `/goal new <描述>` | 建 goal 目录 + current 指针 → 一次 planning 会话 |
| `/goal next` | 推进一条 story（一次全新会话） |
| `/goal run` | 循环推进至 done / 触顶显性报错 |
| `/goal auto [cron 表达式]` | 默认 `*/15 * * * *`；`/goal auto off` 注销 |
| `/goal status`（裸 `/goal` 同义） | 打印进度计数 + GOAL.md 全文 |
| `/goal reset` | 清 current 指针，回显目录（不删文件） |

### FR Coverage Map

FR-1: Story 41.1（skill 注入 + 单步会话 + 边界扫描 + 子命令）
FR-2: Story 41.2（run 循环）
FR-3: Story 41.2（metadata 透传）
FR-4: Story 41.3（cron auto）
NFR-5 收尾（文档/回归/冒烟）: Story 41.4

## Epic List

### Epic 41: 目标驱动开发——/goal 启动 skill 执行工作流

HeAgent 交互 CLI 获得 BMAD 式目标驱动开发入口：`/goal <描述>` 启动 goal skill（方法论唯一载体，人可直接编辑定制），框架只做机制层——每步（一次规划 / 一条 story）开一个全新 SubAgent 会话（fresh context，token 阈值经 WindowReset 清窗续跑），会话边界即 story 边界；进度落盘 `.heagent/goals/<id>/GOAL.md` 由 LLM 按 skill 契约维护，代码只扫机器可读标记判边界、违约显性报错；`/goal auto` 提供 cron 无人值守推进（完成自动注销）。用户由此获得「一条命令 → skill 驱动的逐 story 交付流」，且方法论迭代零代码变更。

**FRs covered:** FR-1, FR-2, FR-3, FR-4

内部 story 顺序：41.1（机制底座，全部后续 story 依赖）→ 41.2（run 循环 + 观测标记，独立增量）→ 41.3（cron auto，依赖 41.1 的推进路径）→ 41.4（收尾：文档/回归/冒烟）。

### Story 41.1: /goal 启动 skill 与单步工作流（FR-1）

As a 框架使用者,
I want 在交互 CLI 里用 `/goal <描述>` 启动 goal skill 并获得 planning 产物 GOAL.md，用 `/goal next` 以全新会话推进一条 story，用 `/goal status`/`/goal reset` 查看/停用,
So that 工作流由 skill 契约驱动、每步独立上下文、进度落盘可续跑。

**Acceptance Criteria:**

**Given** `.heagent/skills/goal/SKILL.md` 存在，**When** `/goal <描述>`，**Then** 创建 `.heagent/goals/<uuid4().hex[:8]>/`（goal.txt + current 指针原子写）并以确定性注入 skill 正文跑一次 planning 会话（全新 AgentLoop/RunContext，`WindowResetConfig(threshold=settings.window_reset_threshold)`）
**And** 会话结束后 GOAL.md 存在、首行 status=executing、≥1 条 story（不合规 = 显性失败回显，目录保留可重试）
**Given** 已有活跃 goal，**When** `/goal next`，**Then** prompt 含 skill 正文 + GOAL.md 全文 + 单 story 任务指令；会话边界 = story 边界（`.heagent/runs/` 每条 story 独立 run 记录）
**Given** 裸 `/goal` 或 `/goal status`，**When** 执行，**Then** 打印进度计数（done/total + status）与 GOAL.md 全文
**Given** `/goal reset`，**When** 执行，**Then** current 指针清空、goal 目录保留
**Given** skill 缺失，**When** 任意 goal 子命令，**Then** 显性报错并附创建指引
**Given** 会话返回但 GOAL.md 未被写 / 无合法 status 行，**Then** 显性报错（run 白跑但可检测）
**And** 子命令缺参打印用法不 `input()` 追问；会话期间 Ctrl+C 打断兜底回显「状态在盘，`/goal next` 可续跑」
**And** 工作区已有 SKILL.md 草稿（含 Pattern/frontmatter，可被 SkillStore 相似度匹配），采纳为基线定稿

### Story 41.2: /goal run 连续推进与 run 观测标记（FR-2, FR-3）

As a 框架使用者,
I want `/goal run` 自动连续推进 story 直至 done，且每个 goal 会话的运行记录可按 goal 过滤,
So that 无需逐条手动触发，事后可审计哪个 run 属于哪个 goal。

**Acceptance Criteria:**

**Given** 活跃 goal，**When** `/goal run`，**Then** 循环推进 story 至 done（每条仍是一个全新会话，边界语义与 `/goal next` 一致）
**And** 全部 checkbox 勾选或 `status: done` 时循环停止并回显；触 max rounds（常量默认 10）显性报错不静默
**Given** SubAgent 构造传 `metadata={"goal_id":..., "goal_kind":...}`，**Then** 子 run 快照 metadata 含这些键且 `kind=subagent` 保留（可按 goal_id 过滤）
**Given** metadata 缺省 None，**Then** 行为与现状一致（既有 `tests/test_sub_agent.py` 全绿，回归锁定）
**And** run 循环内单步失败（result.success=False）停止循环并回显错误（不静默续推）

### Story 41.3: /goal auto cron 无人值守（FR-4）

As a 框架使用者,
I want `/goal auto <cron>` 注册定时推进，goal 完成或 blocked 后 job 自动注销,
So that 长目标无需人守着 CLI 也能持续推进，且完成后自动收口。

**Acceptance Criteria:**

**Given** `/goal auto [cron 表达式]`（默认 `*/15 * * * *`），**When** 执行，**Then** `JobStore` 注册 prompt 为 `goal-advance <goal_id>` 的 job（落盘 `.heagent/cron/jobs.json`）
**Given** cron tick 且 job prompt 以 `goal-advance ` 前缀开头，**When** `_run_job` 执行，**Then** 分流到 goal 推进路径（与 `/goal next` 同一会话构造）；非前缀 job 走原路径（既有 cron 行为回归锁定）
**Given** goal 达到 done / blocked，**When** 推进路径扫描，**Then** job 自动注销（`list_jobs()` 扫前缀）并回显
**Given** 手动 `/goal next` 与 cron tick 并发，**When** 同时推进，**Then** 进程内锁保证串行（第二次调用等待）
**Given** CLI 退出后重启，**When** scheduler 启动，**Then** 落盘 job 继续被调度（真无人值守）
**And** 无人值守不提升任何权限：审批照走 PolicyEngine fail-safe（拒绝 → blocked → 注销回显）
**And** `/goal auto off` 手动注销当前 goal 的 auto job

### Story 41.4: 文档同步与全量回归收尾（NFR-5）

As a 维护者,
I want frame.md 与总览文档反映 /goal 机制，全量质量门与真实冒烟通过,
So that 架构权威与代码一致、特性交付可信。

**Acceptance Criteria:**

**Given** 41.1–41.3 完成，**When** 收尾，**Then** `docs/frame.md` 增补 /goal（skill 契约、`.heagent/goals/` 目录、cron auto、机制/方法论分层说明）
**And** 全量 `pytest` / `ruff check src tests` / `mypy src` 绿（既有回归零改动）
**And** 手动冒烟：真实 LLM 跑一个 2-story 小 goal——`/goal <描述>` 出 planning → `/goal run` 逐 story 勾选 → `/goal auto */1 * * * *` 定时推进 + 完成自动注销（凭据缺失时记录为人工待办，不阻塞收尾）
**And** sprint-status.yaml 状态流转 + consolidated-overview.md 增量补录
