---
title: 'Dreaming step-04 审查 3 个 LOW defer 收口'
type: 'refactor'
created: '2026-08-12'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'd9e631e439972f7a64b6c633f6506bd6808b1042'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/patches/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Dreaming 模式 step-04 对抗审查（2026-08-12）遗留 3 个 LOW 非阻断 defer：(a) `memory/dream.py` 横向 reach-through 进 `cron.scheduler.CronScheduler._matches` 私有静态（coupling smell）；(b) `DreamScheduler._await_stop` + `CronScheduler._await_stop` 超时分支留下未取回异常的孤儿 task；(c) `_run_dream` CancelledError 总标 `aborted=True`，无法区分 `stop()` 取消 vs 内部自取消。

**Approach:** (a) 把纯 cron 解析器抽到新纯叶子 `heagent/cron/expr.py`，`scheduler`/`dream` 共用，`CronScheduler._matches` 降为薄委托保 API；(b) 两处 `_await_stop` 超时分支挂 `add_done_callback` 取回孤儿 task 异常并清 `_task`；(c) 据 `self._running` 在 `dream_end` details 里区分 `aborted`/`internal_cancel`。

## Boundaries & Constraints

**Always:**
- `cron_matches` 逻辑**逐字搬迁**（weekday 7→0 规范、`zip(..., strict=True)`、字段范围），零行为变更——`test_cron.py`/`test_cron_range.py` 是回归护栏。
- `cron/expr.py` **零 heagent 导入**（纯叶子，类比 `engine.persist`）；`scheduler` 导入它属包内，`dream` 导入它是对纯叶子的正当依赖。
- 保留 `CronScheduler._matches` 为薄委托静态方法（`return cron_matches(expr, dt)`），保 `test_cron.py` 16 处 + 内部 `self._matches` 调用零回归。
- `_await_stop` 的「立即 cancel + 单轮 bounded wait + 超时记 ERROR 放弃」核心语义与 `stop_timeout<=0` fail-closed 校验**不动**——仅补孤儿 task 异常取回。
- 取消信号优先：`_run_dream` 的 `except CancelledError` 仍 `raise`（传播至上层清理链），仅丰富 `dream_end` details 审计字段。

**Ask First:** 无（LOW cleanup，无架构决策；落点 `cron/expr.py` 已在下方 Design Notes 论证）。

**Never:**
- 不跨 `cron`/`memory` 抽共享 `_await_stop`/`_retrieve_task_exception`——两者本就是同构复制（预存模式），跨包共享引新边、违反简约；保持各一份。
- 不改 `dream.py → cron.expr` 之外的 DAG；不动 `engine`；不新增 `agent/` 反向依赖。
- 不接 `web_fetch` 到 `guard_content`（Dreaming AC6，MED，独立 spec，本轮显式排除）。
- 不改 Cron 进程组 kill（Linux-only）/ 其他 deferred 项。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| cron 匹配（expr 独立） | `cron_matches("* * * * *", dt)` | True；6 字段/非法 → False 或 ValueError（逐字同旧） | 与旧 `_matches` 完全一致 |
| dream 不再 reach-through | grep `memory/dream.py` | `from heagent.cron.scheduler`/`CronScheduler._matches` 零命中 | N/A |
| _await_stop 超时孤儿 | 挂死 task（fake 不响应 cancel），超时 | done callback 取回 task exception（无 "Task exception was never retrieved"），`_task=None` | callback 内 `cancelled()` 守卫后取异常记 ERROR |
| stop() 取消 dream | `_run_dream` 运行中调 `stop()`（`_running=False`） | `dream_end(aborted=True, internal_cancel=False)` | N/A |
| 内部自取消 dream | dream 期间子任务自取消（`_running=True`） | `dream_end(aborted=False, internal_cancel=True)` | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/cron/expr.py` -- **新建**纯叶子：`cron_matches` + `_field_matches`/`_parse_field`/`_parse_range_bounds`/`_validate_range_parts`（自 `scheduler.py` 逐字搬迁）。
- `src/heagent/cron/scheduler.py` -- 删解析器定义；`import cron_matches`；`CronScheduler._matches` 改薄委托；`_await_stop` 超时分支补 callback + 清 `_task`；加模块级 `_retrieve_task_exception`。
- `src/heagent/memory/dream.py` -- `import cron_matches` 取代 `CronScheduler`；2 处调用改写 + docstring；`_await_stop` 同 scheduler 改；`_run_dream` CancelledError details 据 `_running` 区分；加 `_retrieve_task_exception`。
- `tests/test_cron_range.py` -- `_parse_field` 导入改指 `heagent.cron.expr`。
- `tests/test_cron.py` / `tests/test_dream.py` -- 零改动（保回归）+ 新增用例。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/cron/expr.py` -- 新建纯叶子，逐字搬迁 5 个解析符号（`cron_matches` 由原 `_matches` 改名）。
- [ ] `src/heagent/cron/scheduler.py` -- 删定义、import `cron_matches`、`_matches` 薄委托、`_await_stop` 补孤儿取回 + `_retrieve_task_exception`。
- [ ] `src/heagent/memory/dream.py` -- 去 `CronScheduler` 导入换 `cron_matches`、更新 docstring/注释、`_await_stop` 对称改、`_run_dream` details 区分。
- [ ] `tests/test_cron_range.py` -- 导入改 `cron.expr`。
- [ ] `tests/test_dream.py` / `tests/test_cron.py` -- 新增：expr 独立可用、dream 不 import `cron.scheduler`、`_await_stop` 超时取回（无 asyncio 警告）、`_run_dream` 两种取消语义。

**Acceptance Criteria:**
- AC1 Given `cron.expr` 导入, when `cron_matches("* * * * *", <dt>)`, then True。
- AC2 Given dream.py, when grep, then `cron.scheduler`/`CronScheduler._matches` 零命中且触发行为不变（`test_dream.py` 绿）。
- AC3 Given `CronScheduler._matches` 薄委托, when 既有 16 处 + 范围测试, then 全绿（零回归）。
- AC4 Given 挂死 task 超时, when `_await_stop` 超时分支, then 孤儿 task 异常被 done callback 取回（无 "Task exception was never retrieved"），dream + cron 对称。
- AC5 Given `_run_dream` 运行, when 内部自取消（`_running=True`）/ `stop()` 取消（`_running=False`）, then 分别 `internal_cancel=True` / `aborted=True`。
- AC6 Given `stop_timeout<=0`, when 构造, then raise（既有校验不变）；正常 stop 路径零回归。
- AC7 pytest 全绿 / ruff 零新增 / mypy clean。

## Design Notes

- **`cron/expr.py` 落点（非 deferred-work 原建议的 `tools/cron_expr.py`）**：解析器零 heagent 导入，自然属 `cron` 包；`cron → tools`（原建议）反让 cron 为拿自家解析器而依赖 tools，更别扭。`memory → cron.expr` 是对纯叶子的依赖，与既有 `memory → engine.persist` 同构，区别于原 smell（伸手进 `CronScheduler` 私有静态）。`CronScheduler._matches` 保留薄委托以避免改 `test_cron.py` 16 处调用（最小 churn）。
- **`_retrieve_task_exception` 取消守卫**：done callback 内先 `if task.cancelled(): return`——Cancelled task 无需 retrieve，且 `task.exception()` 对 cancelled task 会抛 `CancelledError`，须守卫；其后 `task.exception()` 取非 None 异常记 ERROR 并标记 retrieved。两文件各一份，对齐既有 `_await_stop` 同构复制模式。
- **`(c)` 不变量来源**：`stop()` 首行置 `_running=False` 后才 cancel，故 stop 取消时 handler 见 `_running=False`；内部自取消时 `_running` 仍 True。

## Verification

**Commands:**
- `pytest tests/test_dream.py tests/test_cron.py tests/test_cron_range.py -q` -- expected: 全绿。
- `ruff check src tests` -- expected: 零新增。
- `mypy src` -- expected: clean。

## Review Findings（2026-08-12，inline 对抗审查）

预算约束（会话 82% 上下文）下采用 inline Blind Hunter + Edge Case Hunter 审查（替代并行 subagent 面板）；改动 surgical、全量 994 passed / ruff clean / mypy clean。逐项核验 AC1–AC7 全 PASS。

**patch（0 项）**：无。

**defer（0 项）**：无。`memory/dream → cron.expr` 包级边按 Design Notes 是纯叶子依赖（类比 `engine.persist`），by-design 非缺陷——frame.md / CLAUDE.md DAG 注记更新见归档步骤。

**reject（核验通过的边界，记此备查）**：
- `cron_matches` 逐字搬迁，行为零变更——`test_cron.py` 16 处 `CronScheduler._matches` + `test_cron_range.py` 全绿是回归护栏。
- `_retrieve_task_exception` 的 `if task.cancelled(): return` 守卫必要——`task.exception()` 对 cancelled task 会抛 `CancelledError`；done callback 内 task 已 done，无 InvalidStateError 风险。
- `_await_stop` 超时分支 `_task=None` 仅在 `if pending:` 触发；clean stop 路径保留 `_task`（`test_stop_clean_no_error_on_sleep` 仍断言 `_task is not None and _task.done()`，绿）。
- (c) `_running` 单线程 asyncio 下无竞态：`stop()` 同步置 `_running=False` 后才 `task.cancel()`，except handler 读到稳定值。

