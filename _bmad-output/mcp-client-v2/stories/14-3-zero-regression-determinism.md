---
baseline_commit: 6ccc4530b5fb2004b2df85411cc164af05b8b4c0
---

# Story 14.3: 零回归护栏 + 治理确定性验证

Status: done

## Story

As a HeAgent 开发者,
I want annotations→verdict 路径存在不触达任何 LLM 的单元测试，且既有 V1 MCP + 19 个内置工具测试全绿,
So that 治理确定性可证（硬约束「确定性逻辑交给代码」），且 V2 不破坏既有行为（SM-4）。

> **本 story 是 Epic A（写操作治理）的测试验证收尾**——确认 Story 14-1（数据管线）+ Story 14-2（裁决逻辑）的测试完备性，覆盖 FR-A6 确定性证明 + SM-4 零回归护栏 + AD-2 步 0 fail-safe 不误伤内置工具。

## Acceptance Criteria

**AC-1（FR-A6，AD-3：确定性可单测）**
**Given** 一个不依赖任何 provider 的单元测试
**When** 构造 destructive / readOnly / 缺省三种 annotations 调用 PolicyEngine
**Then** 断言 verdict 分别为 `APPROVAL_REQUIRED` / 非 approval / `APPROVAL_REQUIRED`，全程无 LLM 调用

**AC-2（SM-4，AR-9：零回归护栏）**
**Given** 既有 19 个内置工具测试套件 + V1 MCP 测试套件
**When** 运行全量测试
**Then** 全绿，覆盖率不低于基线

**AC-3（AD-2：内置工具不被 fail-safe 误伤）**
**Given** 一个针对步 0 前置闸门的对抗测试（内置工具 `schema=None`）
**When** 断言其 verdict
**Then** 不为 `APPROVAL_REQUIRED`（除非被既有显式 `approval_tools` 命中），证明 fail-safe 未误伤内置工具

## Tasks / Subtasks

- [x] **Task 1: 确定性单测** (AC: #1)
  - [x] `test_destructive_hint_requires_approval` — 无 LLM provider
  - [x] `test_readonly_hint_passes_without_approval` — 无 LLM provider
  - [x] `test_no_annotations_failsafe_requires_approval` — 无 LLM provider

- [x] **Task 2: 零回归验证** (AC: #2)
  - [x] 全量测试 570 passed（含既有 V1 MCP + 19 内置工具）
  - [x] 新增 11 个 TestPolicyAnnotationGate 测试不破坏既有基线

- [x] **Task 3: 内置工具 fail-safe 防盗测** (AC: #3)
  - [x] `test_builtin_tool_schema_none_skips_annotation_gate` — schema=None 时不为 APPROVAL_REQUIRED
  - [x] `test_builtin_tool_with_approval_tools_still_works` — 内置工具被既有 approval_tools 命中时仍 APPROVAL_REQUIRED（既有行为不受影响）
  - [x] `test_non_mcp_tool_with_schema_does_not_failsafe` — 非 MCP 工具传 schema.annotations=None 不被 fail-safe

## Dev Notes

- 所有测试同步（无 async、无 provider、无网络），验证纯函数确定性本质。
- 测试类 `TestPolicyAnnotationGate` 类级别常量 `_MCP_CALL` 和 `_BUILTIN_CALL` 复用。
- 全量回归验证确认 `pytest` 570 passed，V1 MCP 测试 + 19 内置工具测试无一退步。
- `test_non_mcp_tool_with_schema_does_not_failsafe` 验证：file_read 虽传了 schema(annotations=None)，但 `_is_mcp_tool` 返回 False → 跳过注解裁决 → 非 APPROVAL_REQUIRED。这是 AD-2 的「MCP 工具 + schema.annotations is None」才触发 fail-safe 的精确语义。

## File List

- `tests/test_engine_p0.py::TestPolicyAnnotationGate` — 11 个测试用例（其中 3 个确定性单测 + 4 个零回归护栏 + 4 个授权/内置工具防盗测）
- 新增 11 测试用例内嵌于既有 `test_engine_p0.py`，不新建测试文件（brownfield 扩展）

## Change Log

- 2026-07-17：Story 14-3 实现完成——确定性验证、零回归护栏、内置工具防盗测全覆盖。Status → done。
