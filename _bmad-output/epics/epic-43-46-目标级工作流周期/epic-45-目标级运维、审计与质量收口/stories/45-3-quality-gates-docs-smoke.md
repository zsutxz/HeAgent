---
title: '45-3 目标工作流质量门、文档同步与真实冒烟'
type: 'feature'
created: '2026-09-01'
status: 'done'
review_loop_iteration: 0
baseline_commit: '8369cde56d03af6bc501447c5957973561fd087e'
context:
  - 'E:/AI/HeAgent/docs/frame.md'
  - 'E:/AI/HeAgent/docs/iteration.md'
  - 'E:/AI/HeAgent/_bmad-output/epics/epic-43-46-目标级工作流周期/epics.md'

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** Epic 43-44 已交付目标工作流状态迁移、checkpoint、恢复和 Token rollover，但质量门、文档状态与真实小目标冒烟证据尚未形成一个可重复的收口入口，维护者难以确认闭环仍可回归。

**Approach:** 增加针对目标工作流的确定性回归/冒烟测试入口，执行既有 pytest、ruff、mypy 质量门，并同步架构、迭代记录和 BMAD 状态文档。冒烟使用 StubProvider 或无凭据时明确记录 blocked，不把外部 LLM 可用性伪装成通过。

## Boundaries & Constraints

**Always:** 复用现有 `WorkflowOrchestrator`、`WorkflowCheckpointStore`、`TokenBudgetManager`、`StubProvider` 和 `/goal` 测试夹具；确定性质量门由命令和测试控制；外部凭据不可用时保留可诊断的 blocked 证据；文档必须反映实际代码和测试结果。

**Ask First:** 若实现需要修改既有 `/goal`、workflow 状态模型或公共 CLI 输出契约，先暂停并请求确认；本故事默认只新增测试、检查入口和文档。

**Never:** 不引入新的工作流状态所有权；不让 LLM 决定阶段路由或测试通过与否；不把真实网络/凭据测试设为默认质量门；不宣称路径围栏、SafetyGuard 或 engine sandbox 是 OS 安全边界；不删除既有回归测试或降低覆盖率门槛。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|-----------------------------|----------------|
| Deterministic smoke | StubProvider、至少两个 story 的小目标 | 从 planning 推进到 done 或显式 blocked，并留下 workflow/checkpoint/审计证据 | 断言状态、产物和下一动作，禁止静默成功 |
| Missing provider credentials | 未配置外部 LLM 凭据 | 默认测试仍可运行；真实冒烟标为 blocked 并说明原因 | 不发送网络请求，不伪造完成 |
| Quality gate failure | pytest、ruff 或 mypy 任一失败 | 命令以非零状态退出并保留失败输出 | 文档不得记录为通过 |
| Corrupt workflow evidence | 损坏 workflow/checkpoint 文件 | 测试验证显式失败/blocked，现有状态文件保留 | 不静默重置或生成完成标记 |

</frozen-after-approval>

## Code Map

- `tests/test_engine_workflow.py` -- Epic 43-44 状态迁移、checkpoint、幂等、Token rollover 与恢复信封的现有确定性回归基线；新增收口断言应复用其夹具和模型。
- `tests/test_goal_command.py` -- `/goal` CLI 创建、推进、暂停、恢复、审计和兼容性行为；用于验证 CLI 质量门不改变既有路径。
- `tests/test_run_tree.py` -- 运行树/审计元数据断言；用于确认小目标冒烟留下可追踪 run 证据。
- `src/heagent/engine/workflow.py` -- `WorkflowOrchestrator`、`WorkflowCheckpointStore`、`TokenBudgetManager` 与 `RecoveryEnvelope` 的公共实现，测试只调用现有 API。
- `src/heagent/cli.py` -- `/goal` 子命令分发与状态/审计输出；只读核对，不改变既有行为，除非测试暴露实际缺口且经确认。
- `.github/workflows/ci.yml` -- 当前 pytest、coverage、ruff、mypy 与安全门禁；必要时补充目标工作流 smoke job，但保持默认门禁可在无凭据环境运行。
- `docs/frame.md` -- 架构权威，补充目标级 CLI、workflow/checkpoint、Token 分段和质量边界的实际状态。
- `docs/iteration.md` -- 迭代时间线和当前状态，记录 Epic 43-45 收口证据及 blocked 约束。
- `_bmad-output/consolidated-overview.md` -- Epic 总览与状态矩阵，更新 Epic 45.3 完成证据；不得与 `_bmad-output/sprint-status.yaml` 冲突。
- `_bmad-output/sprint-status.yaml` -- 唯一 sprint 状态源；测试和文档收口通过后将 `45-3-quality-gates-docs-smoke` 置为 done，并保留历史状态说明。

## Tasks & Acceptance

**Execution:**
- [x] `tests/test_goal_workflow_smoke.py` -- 新增无网络、StubProvider 驱动的至少两 story 目标冒烟，覆盖完成与显式 blocked 分支，并断言 checkpoint、workflow 状态和审计证据。
- [x] `tests/test_engine_workflow.py`, `tests/test_goal_command.py`, `tests/test_run_tree.py` -- 核对现有回归断言；无缺口时保持公共行为不变。
- [x] `.github/workflows/ci.yml` 与 `scripts/quality_gate.py` -- 提供可重复的目标工作流质量门命令入口，默认不依赖外部凭据，失败返回非零状态。
- [x] `docs/frame.md`, `docs/iteration.md`, `_bmad-output/consolidated-overview.md` -- 同步 Epic 43-45 的实现、测试、Token、审计和安全边界描述。
- [x] `_bmad-output/sprint-status.yaml` -- 验证完成后更新 45.3 状态为 done。

**Acceptance Criteria:**
- Given StubProvider 和临时 goal 目录，when 执行目标工作流 smoke，then 至少两个 story 可推进到 done 或明确 blocked，且 workflow/checkpoint/run 审计证据可读取。
- Given 缺失凭据或外部服务不可用，when 执行默认质量门，then 测试不发起网络调用，真实冒烟结果显式为 blocked，命令仍以可诊断结果结束。
- Given 任一 pytest、ruff 或 mypy 检查失败，when 执行质量门入口，then 返回非零退出码并保留失败输出，不报告通过。
- Given 文档和 sprint 状态更新，when 维护者查阅架构、迭代和总览，then Epic 43-45 状态、checkpoint/Token/审计语义及 OS 沙箱非边界声明彼此一致。
- Given 现有回归测试集，when 执行目标工作流新增测试与原有 `/goal`、SkillStore、AgentLoop 测试，then 原有行为保持通过且无覆盖率门槛降低。

## Design Notes

质量门按“默认本地确定性检查”和“可选外部冒烟”分层：StubProvider 冒烟验证编排闭环；真实 LLM 冒烟只作为显式、可审计的手工/CI workflow_dispatch 步骤。测试不得直接编辑 Story 看板来伪造完成，workflow.json 只保存运行时元数据，`GOAL.md` 仍是 Story 状态的权威来源。

## Verification

**Commands:**
- `pytest tests/test_goal_workflow_smoke.py tests/test_engine_workflow.py tests/test_goal_command.py tests/test_run_tree.py` -- expected: 全部通过，无网络依赖。
- `pytest -m "not integration and not benchmark" --cov=heagent --cov-fail-under=87` -- expected: 默认回归和覆盖率门通过。
- `ruff check src tests` -- expected: 无 lint 错误。
- `ruff format --check src tests` -- expected: 格式检查通过。
- `mypy src` -- expected: strict 类型检查通过。

## Suggested Review Order

**Workflow smoke**

- 真实 CLI 两 story 冒烟
  [`test_goal_workflow_smoke.py:115`](../../../../../tests/test_goal_workflow_smoke.py#L115)

- checkpoint 与审计证据
  [`test_goal_workflow_smoke.py:20`](../../../../../tests/test_goal_workflow_smoke.py#L20)

**Quality gates**

- 统一门禁与失败传播
  [`quality_gate.py:1`](../../../../../scripts/quality_gate.py#L1)

- CI 无凭据 smoke job
  [`ci.yml:69`](../../../../../.github/workflows/ci.yml#L69)

**Documentation and status**

- 架构边界与运行入口
  [`frame.md:856`](../../../../../docs/frame.md#L856)

- 迭代与 Epic 状态同步
  [`iteration.md:291`](../../../../../docs/iteration.md#L291)

- sprint 唯一状态源
  [`sprint-status.yaml:451`](../../../../sprint-status.yaml#L451)
