---
baseline_commit: 6ccc4530b5fb2004b2df85411cc164af05b8b4c0
---

# Story 14.2: PolicyEngine 注解裁决闸门（schema kwarg + 固定优先级 + fail-safe 仅 MCP）

Status: done

## Story

As a HeAgent 操作者,
I want destructive MCP 工具调用走审批、readOnly 工具静默放行、缺 annotations 的 MCP 工具 fail-safe 需确认,
So that 写操作不裸跑（防 agent 误删/误建），只读操作不被无脑确认打扰，且危险判定在代码层。

> **本 story 是 Epic A（写操作治理）的裁决层落地**——接 Story 14-1 的数据层（`ToolAnnotations` + `ToolSchema.annotations`），在 `PolicyEngine.evaluate_tool_call` 和 `tool_execution.py` 两端落地 AD-1/AD-2/AD-7。本 story 完成后 MCP 工具的 annotations 驱动审批/放行即可工作（FR-A3/A4/A5/A7）。

## Acceptance Criteria

**AC-1（AD-1：evaluate_tool_call +schema kwarg）**
**Given** `PolicyEngine.evaluate_tool_call` 签名为 `evaluate_tool_call(call, *, context=None, schema=None)`
**When** `agent/tool_execution.execute_tool_call` 在裁决前 `schema = loop.registry.get_schema(call.name)` 并传入
**Then** 两个 evaluate 调用点（正常路径 + ledger 缓存命中复核）都传 schema kwarg
**And** `ToolCall`/`RunContext` 结构不变

**AC-2（FR-A3：destructiveHint → 审批）**
**Given** 一个 `destructiveHint=true` 的 MCP 工具调用且未授权
**When** PolicyEngine 裁决
**Then** 返回 `PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在执行闸门前
**And** 授权后（`metadata.approved_tools` 含该工具名 / `*` / `__mcp__`）放行至后续裁决

**AC-3（FR-A4：readOnlyHint 放行 + 显式策略优先）**
**Given** 一个 `readOnlyHint=true` 的 MCP 工具调用且无其他阻断条件
**When** PolicyEngine 裁决
**Then** 返回非 `APPROVAL_REQUIRED`（落 DIRECT / 既有沙箱裁决），不因「是 MCP 工具」强制确认
**And** 显式策略 `approval_mcp_tools=True`（或 `approval_tools` 命中）即使是 readOnly 也优先 → `APPROVAL_REQUIRED`

**AC-4（FR-A5：缺 annotations fail-safe）**
**Given** 一个 MCP 工具缺 annotations（`schema.annotations` 为 None）
**When** PolicyEngine 裁决
**Then** 按 fail-safe 返回 `APPROVAL_REQUIRED`

**AC-5（AD-2 步 0：schema=None 内置工具零回归）**
**Given** 一个 V1 内置工具调用（`schema=None`）
**When** PolicyEngine 裁决
**Then** 步 0 前置闸门触发：跳过注解裁决，回到既有路径，**绝不**对内置工具触发 fail-safe

**AC-6（FR-A7：idempotent/openWorld 不进裁决）**
**Given** 一个 MCP 工具声明 `idempotentHint=true` 或 `openWorldHint=true`
**When** PolicyEngine 裁决
**Then** verdict 不因此改变

## Tasks / Subtasks

- [x] **Task 1: `policy.py` `_requires_approval` 加注解感知裁决逻辑** (AC: #2-#6)
  - [x] 修复优先级：显式策略优先 → destructive → readOnly → fail-safe（缺 annotations）→ schema=None（内置工具跳过）
  - [x] MCP 工具 + destructiveHint → APPROVAL_REQUIRED
  - [x] MCP 工具 + readOnlyHint → 免审批
  - [x] MCP 工具 + annotations=None → fail-safe APPROVAL_REQUIRED
  - [x] schema=None（内置工具）→ 跳过注解裁决回既有路径
  - [x] idempotentHint/openWorldHint 不进入裁决
  - [x] `_approval_reason` 同步更新反映 annotations 触发原因

- [x] **Task 2: `policy.py` `evaluate_tool_call` 签名 + schema kwarg** (AC: #1)
  - [x] 签名增 `schema: ToolSchema | None = None`
  - [x] 步 5 审批调用 `_requires_approval(call, schema=schema)`

- [x] **Task 3: `tool_execution.py` 两处 evaluate 调用点传 schema** (AC: #1)
  - [x] 正常路径：`schema = loop.registry.get_schema(call.name)` 传入
  - [x] 缓存命中复核路径：同样取 schema 传入
  - [x] ToolCall/RunContext 结构不变

- [x] **Task 4: 测试验证** (AC: #2-#6)
  - [x] `test_destructive_hint_requires_approval`
  - [x] `test_destructive_hint_after_approval_grants`
  - [x] `test_readonly_hint_passes_without_approval`
  - [x] `test_explicit_approval_overrides_readonly_hint`
  - [x] `test_no_annotations_failsafe_requires_approval`
  - [x] `test_builtin_tool_schema_none_skips_annotation_gate`
  - [x] `test_builtin_tool_with_approval_tools_still_works`
  - [x] `test_idempotent_hint_does_not_affect_verdict`
  - [x] `test_wildcard_approval_grants_mcp_tool`
  - [x] `test_mcp_wildcard_approval_grants_mcp_tool`
  - [x] `test_non_mcp_tool_with_schema_does_not_failsafe`

## Dev Notes

- 本 story 的裁决逻辑落在 `policy.py` `_requires_approval`；evaluate 入口签名已在 `evaluate_tool_call` 加 `schema` kwarg。
- 两处调用点（正常路径 + 缓存命中复核）均在 `tool_execution.py` `execute_tool_call` 内——两处均已取 `loop.registry.get_schema(call.name)` 再传参。
- **零回归证明**：`schema=None`（内置工具）时 `_requires_approval` 走步 0 前置闸门，不触发 fail-safe，既有 approve/sandbox/block 行为不变。
- `_requires_approval` 内 `ann = schema.annotations` 访问受 `ann is not None` 守卫，缺 annotations 时 `ann=None` 触发步 2c fail-safe。
- `openWorldHint` 未单独加测试——与 `idempotentHint` 同构（均不进裁决），`test_idempotent_hint_does_not_affect_verdict` 覆盖其行为等价性。

## File List

- `src/heagent/engine/policy.py` — `evaluate_tool_call` +schema kwarg；`_requires_approval` 注解感知裁决；`_approval_reason` 注解触发原因
- `src/heagent/agent/tool_execution.py` — 两处 evaluate 调用点传 schema kwarg
- `tests/test_engine_p0.py` — `TestPolicyAnnotationGate` 11 个测试用例

## Change Log

- 2026-07-17：Story 14-2 实现完成——PolicyEngine annotation gate 裁决层全逻辑落地（_requires_approval 固定优先级 + evaluate 入口 schema kwarg + 两处调用点传参 + 11 测试用例全覆盖）。Status → done。
