---
id: 52-3
title: 宿主接线——执行上下文贯通、Git 审计与失败语义
status: planned
parent_epic: E52
priority: P1
depends_on: [52-1, 52-2]
blocks: [52-5]
created: '2026-10-09'
---

# Story 52-3：宿主接线——执行上下文贯通、Git 审计与失败语义

## 用户故事

作为 Goal 负责人，我希望并行 Story 完成后被审计实际写集，越集者显性 FAILED 且该 Goal 永久降级串行，
守规矩 Story 的产物照常入账。

## 范围（宿主侧；引擎面已在 52-1/52-2 交付）

- `src/heagent/goal/application.py`：`StepExecutor` 协议扩展为可收第四参
  `execution: StoryExecutionContext | None = None`；`_run_step_with_inputs` 透传（缺省 None = 现状）。
- `src/heagent/cli/goal.py`：
  - `_goal_execute_step(..., execution=None)`：`execution.write_allowlist` 非空 →
    `_goal_session(..., write_allowlist=...)` 传 SubAgent（52-1 参数联动，端到端围栏）；
  - 新增 `_audit_story_writes(...)`：SubAgent 会话**开始前**采 `ReadOnlyGitPort.evidence()` 的
    changed/untracked 集为 before 基线，会话 + 质量门结束后再采 after，`Δ = after \ before`；
    判负式 `(Δ.changed \ ∪兄弟write_set \ 宿主自写产物路径) 非空` → 返回判负理由；
    untracked 增量发 `workflow_write_audit` 警告事件（仿 `_emit_goal_gate_event` 隔离 try）；
    非 Git（`GitPortError`）跳过审计并发跳过说明事件；
  - 判负 → 返回 `WorkflowStepResult(FAILED, reason=<越集路径清单>, write_violation=True)`；
  - 模块级 `asyncio.Lock` 串行化并行 Story 的 `_goal_structured_gate`（LLM 会话并行、门命令串行）。

## 验收标准

1. 并行 Story 的 SubAgent run 带 allowlist——端到端：工具链越集写被拦（与 52-1 联动）。
2. tracked 增量越集 → FAILED + reason 列出越集路径 + 撤销闩置位；重启后该 Goal 串行。
3. 兄弟写集内的路径不误伤（构造双 Story 并发写各自声明路径的用例）。
4. untracked 增量只发 `workflow_write_audit` 警告事件不判负（含 `.heagent/tmp/` 验证夹具场景回归）。
5. 非 Git 项目跳过审计、围栏仍生效；宿主自写产物（`goal_step_artifact_path`）不计入违规。
6. 并行质量门经锁串行——并发探针测试断言门命令无重叠执行。
7. 串行 step（`max_parallel_stories=1`）宿主路径零变化（既有 CLI 测试零改动通过）。

## 任务

- [ ] TDD：先写 `tests/test_story_write_audit.py`（RED）——tracked 判负、兄弟排除、untracked 警告、
      非 Git 跳过、宿主产物排除、write_violation 传导、门锁串行探针。
- [ ] 实现协议透传 + 审计 + 事件 + 判负 + 门锁（GREEN）。
- [ ] 与 52-1/52-2 联动的端到端冒烟。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_story_write_audit.py tests/test_goal_application.py -q   # 后者按实际文件名更正
pytest tests/test_story_parallel_scheduling.py tests/test_story_scheduling_integration.py -q
pytest
ruff check src tests
mypy src
```
