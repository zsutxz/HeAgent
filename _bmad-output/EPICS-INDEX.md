# HeAgent — Epic 总目录（EPICS-INDEX）

> **本文件是 `_bmad-output` 的 epic 级总索引**（2026-08-19 重组）。目录布局：
>
> | 位置 | 内容 |
> |------|------|
> | `epic-*/stories/` | 可执行 story 文件，按 epic 归档（仅建有 story 的 epic） |
> | `_cycles/<周期>/` | 周期级规划文档（prd / brief / architecture / epics / sprint-status / reviews / retrospective） |
> | `patches/` | 计划外补丁与技术债，跨周期扁平（见各 epic 节「相关 patches」映射） |
>
> **权威进度 = `_cycles/baseline/sprint-status.yaml`**（全部 epic 状态以此为准，含各周期 sprint-status 整合）。
> Epic 编号内幕：周期内部曾用 A/B/C/S 前缀编号，主线统一映射见下表（11-13=MCP V1 内部 1-3；15/16/17=A/B/C；19/20=健壮性周期 A/C；S1-S4=沙箱周期）。

## Epic 一览（全部 done）

| Epic | 主题 | 所属周期 | Story 归档 |
|------|------|----------|-----------|
| 1 | 项目基础设施与 LLM 通信 | baseline | `epic-01-基础设施与LLM通信/stories/`（1-1~1-5） |
| 2 | 自主 Agent 核心循环 | baseline | —（无独立 story 文件） |
| 3 | 对话持久化与上下文管理 | baseline | — |
| 4 | 自学习记忆系统 | baseline | — |
| 5 | 多 Agent 并行编排 | baseline | — |
| 6 | Context Files 自动加载 | baseline | — |
| 7 | SOUL.md 人格系统 | baseline | — |
| 8 | Memory Nudge 记忆提醒 | baseline | — |
| 9 | Skill Curator 技能策展 | baseline | — |
| 10 | Cron 定时调度 | baseline | — |
| 11 | MCP 工具桥接（V1 核心） | mcp | — |
| 12 | GitHub 只读验收（V1 场景） | mcp | — |
| 13 | 安全边界与开源可用（V1 收尾） | mcp | — |
| 14 | MCP v1→v2 升级准备（annotations） | mcp | `epic-14-MCP升级准备/stories/`（14-1~14-4） |
| 15 | 写操作治理（=内部 Epic A） | mcp | `epic-15-写操作治理/stories/`（15-1~15-2） |
| 16 | Resources 发现与读取（=内部 Epic B） | mcp | `epic-16-Resources发现与读取/stories/`（16-1~16-3） |
| 17 | Prompts CLI slash 渲染注入（=内部 Epic C） | mcp | — |
| 18 | 内置工具扩展（git + path safety） | mcp | — |
| 19 | 健壮性硬化（=健壮性周期 Epic A） | robustness-hardening | `epic-19-健壮性硬化/stories/`（19-1） |
| 20 | 质量工程化（=健壮性周期 Epic C） | robustness-hardening | — |
| 21 | Coverage 工程化 | quality-engineering | — |
| 22 | Benchmark 重构 | quality-engineering | — |
| 23 | Docker 硬化 | quality-engineering | — |
| 24 | CI 效能与安全左移 | quality-engineering | — |
| 25 | GUI 流式聊天（最小可跑） | gui | `epic-25-流式聊天/stories/`（25-1~25-3） |
| 26 | GUI 工具可视化 + 斜杠命令 | gui | `epic-26-工具可视化与斜杠命令/stories/`（26-1~26-3） |
| 27 | GUI 管理面板 | gui | `epic-27-管理面板/stories/`（27-1~27-3） |
| 28 | GUI 可观测性 | gui | `epic-28-可观测性/stories/`（28-1~28-3） |
| 29 | 运行时审批闭环 | interaction | — |
| 30 | 会话恢复入口 | interaction | — |
| 31 | 斜杠命令系统 | interaction | — |
| 32 | Hooks 系统 | interaction | — |
| 33 | Plan Mode / 只读模式 | interaction | — |
| 34 | 配置文件驱动角色 + 成本估算 | interaction | — |
| 35 | CLI 体验优化 + 技术债收尾 | interaction | — |
| S1 | 沙箱 profile 映射（profile→argv + contextvar） | sandbox-hardening | `epic-S1-沙箱profile映射/stories/`（S1-1~S1-2） |
| S2 | 沙箱可用性降级 + 配置入口 | sandbox-hardening | `epic-S2-沙箱配置入口/stories/`（S2-1~S2-2） |
| S3 | 沙箱纵深加固（进程组 kill + workspace 隔离） | sandbox-hardening | `epic-S3-沙箱纵深加固/stories/`（S3-1~S3-2） |
| S4 | 沙箱可观测 + 安全声明收尾 | sandbox-hardening | `epic-S4-沙箱可观测收尾/stories/`（S4-1~S4-2） |

> Epic 6 编号冲突注记：`_cycles/mcp/epics-integration.md`（2026-06-03）自称「Epic 6: AgentLoop 全模块集成」，其后自学习周期重新占用 Epic 6 = Context Files 自动加载（以 sprint-status 为准）。该文视作「Epic 1-5 之后的集成补丁」历史归档。

## 各周期文档与 epic 明细

### baseline（Epic 1-10，主线规划周期，冻结决策）

- 周期文档：`_cycles/baseline/`（`prd.md`·`brief.md`·`architecture.md`·`epics.md`（Epic 1-5）·`epics-self-learning.md`（Epic 6-10）·`prd-decision-log.md`·`brief-decision-log.md`·`spec-dreaming-memory-consolidation.md`·`sprint-status.yaml`）
- 相关 patches：
  - Epic 1（provider 容错）：`patches/p0-provider-hardening.md`、`patches/p0-hardening-review-diff.txt`、`patches/retrospective-p0-tech-debt.md`
  - Epic 3：`patches/3-3-token-counter.md`
  - Epic 4（记忆/巩固）：`patches/spec-dreaming-memory-consolidation.md`、`patches/spec-dreaming-defer-cleanup.md`
  - Epic 5：`patches/5-1-subagent-context-injection.md`、`patches/epic-5-context.md`
  - Epic 10（Cron）：`patches/spec-cron-stop-timeout.md`
- engine/ 为 epic 外 P0 增量（见 `docs/frame.md` 4.12）：`patches/retrospective-engine-p5.md`

### mcp（Epic 11-18，MCP Client 集成周期，三阶段，2026-08-18 合并）

- 周期文档：`_cycles/mcp/`（`prd.md`·`brief.md`·`architecture.md`·`epics.md`（三阶段整合分解）·`epics-integration.md`（归档集成文）·`decision-log.md`·`poc-readiness-report.md`·`retrospective-epic-13.md`·`reviews/_v1·_v2·_upgrade/`·`README.md`·`sprint-status.yaml`）
- 相关 patches：
  - Epic 11（MCP FR-3 断连注销 / 生命周期）：`patches/fr3-mcp-auto-unregister.md`、`patches/spec-mcp-shutdown-timeout.md`
  - Epic 13（安全边界 DP-4）：`patches/spec-dp4-mcp-safety-guard.md`、`patches/spec-dp4-mcp-result-guard.md`、`patches/spec-mcp-user-injection-signatures.md`

### robustness-hardening（Epic 19-20，健壮性与质量硬化）

- 周期文档：`_cycles/robustness-hardening/`（`prd.md`·`brief.md`·`ARCHITECTURE-SPINE.md`·`epics.md`（内部 Epic A→19 / C→20）·`sprint-status.yaml`）

### quality-engineering（Epic 21-24，纯工程配置周期，不改 src）

- 周期文档：`_cycles/quality-engineering/`（`prd.md`·`brief.md`·`architecture.md`·`epics.md`（21 Coverage / 22 Benchmark / 23 Docker / 24 CI）·`sprint-status.yaml`（已归档））

### sandbox-hardening（Epic S1-S4，Sandbox 硬化）

- 周期文档：`_cycles/sandbox-hardening/`（`prd.md`·`brief.md`·`ARCHITECTURE-SPINE.md`·`epics.md`·`sprint-status.yaml`）
- 相关 patches：`patches/spec-engine-sandbox-backend.md`（S1 前置）、`patches/spec-sandbox-timeout-validation.md`、`patches/spec-sandbox-cancel-signal-preservation.md`、`patches/spec-sandbox-reap-robustness.md`

### gui（Epic 25-28，GUI 终端界面）

- 周期文档：`_cycles/gui/`（`prd.md`·`brief.md`·`epics.md`·`sprint-status.yaml`）

### interaction（Epic 29-35，交互与可扩展层周期，2026-08-19 收官）

- 周期文档：`_cycles/interaction/`（`prd.md`·`brief.md`·`epics.md`（29/30 正文 + 31-35 Backlog 表）·`retrospective.md`）
- 相关 patches：`patches/cli-status-bar.md`（CLI 交互，关联 Epic 35）

### 跨周期（无单一 epic 归属）

- `patches/deferred-work.md`、`patches/spec-deferred-low-cleanup.md`（defer 项收尾）
- `patches/code-review-2026-07-20.md`（全仓审查）
- `patches/spec-business-data-integration.md`（独立业务 spec）
- 根级汇总：`consolidated-overview.md`、`retrospective-all-cycles.md`、`README.md`
