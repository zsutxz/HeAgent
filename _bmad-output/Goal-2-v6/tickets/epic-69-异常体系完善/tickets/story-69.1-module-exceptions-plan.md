---
title: 'Story 69.1 为核心模块定义专用异常'
type: chore
ticket: 1
created: '2026-11-18'
status: done
baseline_revision: 'b4d0e79'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/pub/exceptions.py'
---

## Intent

`pub/exceptions.py` 只有 9 个类，engine 与 agent 侧没有专用异常（都靠通用 `RuntimeError`/`ValueError` 表达），
票面要求 provider / tool / engine / agent 各 ≥3 个专用异常。

**Approach：** 在 `pub/exceptions.py` 补齐四类专用异常（provider：认证/限流/超时/响应格式；tool：参数/执行/未注册；
engine：台账/策略执行/工作流；agent：循环上限/子代理/上下文预算），并把现有 raise 点改到更精确的类型上
（新增类必须有人在真实路径 raise，否则不加）。

## Verify

- 四个模块各 ≥3 个专用异常（测试按类属性 `category` 计数断言）；
- 每个新增类至少一个真实 raise 点（测试/grep 双判据：类被 `raise` 引用）；
- 现有异常类名与 isinstance 关系不变（`ProviderError` 仍是 `HeAgentError` 子类）；
- `tests/fixtures/contract_baselines/exception_types.json` 重新生成后 `--check` 绿。

## Boundaries

- 不为凑数加无人 raise 的类。
- 不改 `network` 的 `HttpErrorCode`（传输层错误码自成一体系）。

## Implementation（实测）

- `pub/exceptions.py` 补 14 个专用异常：provider（认证/限流/超时/响应格式）、tool（参数/执行/未注册）、
  engine（台账/策略执行/工作流）、agent（迭代上限/子代理/续跑）。
- 每个新增类都有真实 raise 点（改造 providers/retry+chain+switchable+key_rotation、engine/executor+ledger+
  workflow_runner、agent/context_runtime+sub+run_lifecycle+resume_runtime+tool_execution、tools/builtins/git、
  tools/mcp/manager、providers/metadata_cache 等既有 raise/校验点）。
- 兼容：需要保留内置异常捕获面的类多继承（`ToolArgumentError(ToolError, ValueError)`、
  `ConfigurationError(HeAgentError, ValueError)` 等）。
- 实测：`pytest tests/test_exceptions.py -q` → 21 例全绿（分类计数、raise 点文本判据、码唯一性）。
