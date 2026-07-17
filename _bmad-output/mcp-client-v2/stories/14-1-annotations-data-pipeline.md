---
baseline_commit: 6ccc4530b5fb2004b2df85411cc164af05b8b4c0
---

# Story 14.1: annotations 数据管线（ToolAnnotations 模型 + ToolSchema.annotations + mapping 透传）

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a HeAgent 开发者,
I want `ToolSchema` 携带 MCP `Tool` 的 annotations 风险 hint 并经 `mcp_tool_to_schema` 自动透传,
So that 下游 `PolicyEngine`（story 14-2）能从**数据**而非 LLM 输出读出工具危险等级（确定性裁决的物质基础）。

> **本 story 是 Epic A（写操作治理）的数据层地基**——只建数据模型 + 透传，**不触碰裁决逻辑**（`policy.py`/`tool_execution.py` 是 14-2 的范围）。本 story 完成后，`ToolSchema.annotations` 已就位但**尚无消费者**（policy 仍走既有路径），这是预期的——14-2 才接上裁决。

## Acceptance Criteria

> verbatim 自 `epics.md` Story A.1（BDD）。AC 编号 = 覆盖的 FR。

**AC-1（FR-A1：ToolSchema 携带 annotations，缺省不破坏 V1）**
**Given** `types.py` 中新增 HeAgent 自有 Pydantic 模型 `ToolAnnotations`（字段 `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`，均默认 `False`；**不透传** `mcp.types.ToolAnnotations` 的第 5 字段 `title`）
**When** 构造 `ToolSchema(name=..., description=..., parameters=...)` 不传 `annotations`
**Then** `ToolSchema.annotations` 为 `None`（缺省），V1 所有既有 `ToolSchema` 构造点零改动通过
**And** `ToolAnnotations` **不依赖** `mcp.types`（types 层不上浮 mcp 依赖，保 DAG）

**AC-2（FR-A2：mcp_tool_to_schema 透传 annotations）**
**Given** 一个 MCP `Tool` 其 `tool.annotations.destructiveHint=True`
**When** `mapping.mcp_tool_to_schema(server_name, tool)` 映射
**Then** 产出的 `ToolSchema.annotations.destructiveHint` 为 `True`（`readOnlyHint=True` 同理）
**And** `tool.annotations` 为 `None` 时，`ToolSchema.annotations` 为 `None`（缺省保守标记，交由 FR-A5 fail-safe 在 14-2 消费）

**AC-3（FR-A7 存储：idempotent/openWorld 透传不裁决）**
**Given** 一个 MCP `Tool` 声明了 `idempotentHint`/`openWorldHint`
**When** 经 mapping 透传
**Then** 两字段保留在 `ToolSchema.annotations` 中（透传存储，供 LLM 参考；本 story 仅存储，裁决与否是 14-2 的事）

## Tasks / Subtasks

- [x] **Task 1: `types.py` 新增 `ToolAnnotations` 模型 + `ToolSchema.annotations` 字段** (AC: #1)
  - [x] 新增 `class ToolAnnotations(BaseModel)`：四字段 `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`，类型一律 `bool`，默认 `False`
  - [x] **不**新增 `title` 字段（mcp 第 5 字段，非裁决信号，丢弃）
  - [x] **不** import `mcp.types`（types.py 保持叶子模块，零外部依赖除 stdlib+pydantic）
  - [x] `ToolSchema` 增字段 `annotations: ToolAnnotations | None = None`（可选，缺省 `None`）
  - [x] 在 `ToolSchema` docstring 补 `annotations` 字段说明（风险 hint，来自 MCP `Tool.annotations`，None=未声明）

- [x] **Task 2: `tools/mcp/mapping.py` `mcp_tool_to_schema` 透传 annotations** (AC: #2, #3)
  - [x] 在 `mcp_tool_to_schema` 内：`tool.annotations is None` → 传 `annotations=None`（保持既有行为，显式）
  - [x] `tool.annotations` 非 None → 构造 HeAgent `ToolAnnotations`，四 hint 各自 `bool(ann.X)` 折叠（见 Dev Notes「tri-state 折叠」）
  - [x] **丢弃** `ann.title`（不传入 HeAgent 模型）
  - [x] 现有 `name`/`description`/`parameters` 映射逻辑零改动

- [x] **Task 3: 测试**（验证意图，非仅跑通流程）(AC: #1, #2, #3)
  - [x] `tests/test_types.py` 增：`ToolAnnotations` 四字段默认 `False`；`ToolSchema` 不传 annotations 时 `.annotations is None`；传 `annotations=ToolAnnotations(destructiveHint=True)` 时正确携带
  - [x] `tests/test_mcp_mapping.py` 增：
    - `tool.annotations=None` → `schema.annotations is None`
    - `tool.annotations.destructiveHint=True` → `schema.annotations.destructiveHint is True`（readOnly 同理）
    - `idempotentHint`/`openWorldHint` 透传保留
    - mcp `readOnlyHint=None`（tri-state 缺省）→ HeAgent `readOnlyHint is False`（折叠验证）
    - `title` 透传后被丢弃（构造后 HeAgent `ToolAnnotations` 无 `title` 属性 / 或断言不携带）
  - [x] 既有 `test_types.py` / `test_mcp_mapping.py` 全部用例零改动通过（零回归护栏，SM-4）

## Dev Notes

### 本 story 的边界（务必看清，防越界）

| 在范围内（14-1 做） | **不在范围内**（14-2 / 14-3 做，勿碰） |
| --- | --- |
| `ToolAnnotations` 模型定义 | `PolicyEngine.evaluate_tool_call` 加 `schema` kwarg（AD-1） |
| `ToolSchema.annotations` 字段 | 注解裁决步 + 固定优先级 + fail-safe（AD-2） |
| `mcp_tool_to_schema` 透传 | `tool_execution.py` 两处 evaluate 调用点传 schema |
| 数据层单测 | 裁决确定性单测（AD-3，FR-A6） |

**关键**：本 story 完成后 `ToolSchema.annotations` 已存在但**无人读取**——`policy.py` 此刻仍完全忽略它。这是设计预期（数据层先行，14-2 接消费者）。不要在本 story 里动 `policy.py`/`tool_execution.py`/`engine/`，否则越界并破坏 epic 的 story 切分。

### 架构约束（AD-1/2/3 对本 story 的硬约束）

摘自 `_bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md`：

- **AD-1**：annotations 经 `ToolSchema` 携带（不是污染 `ToolCall`，不是塞进 `RunContext.metadata`）。→ 本 story 落字段在 `ToolSchema`，正是 AD-1 的数据载体。
- **Consistency Conventions（数据模型）**："`ToolSchema.annotations` 为 HeAgent 自有 Pydantic 模型，字段覆盖四 hint（`readOnly`/`destructive`/`idempotent`/`openWorld`）；`mcp.types.ToolAnnotations` 实际还有第 5 个非决策字段 `title`——V2 **不透传 `title`**（非裁决信号，丢弃）。`annotations` 缺省本身不触发 fail-safe；fail-safe 仅在「MCP 工具 + 缺 annotations」时触发。"
- **Inherited Invariants（DAG）**："`tools/mcp/` 禁从 `agent/` 导入"；"跨模块数据用 Pydantic `BaseModel`"；"`ToolSchema.annotations` 为 HeAgent 自有 Pydantic 模型，**不上浮 `mcp` 依赖进 `types.py`**"。→ **types.py 绝不 import mcp**；mcp→HeAgent 的转换发生在 `mapping.py`（它本就 import mcp）。

### tri-state 折叠（最易猜错的设计点——务必按此实现）

`mcp.types.ToolAnnotations`（已核实 SDK 源码 1.28.0）四 hint 字段类型是 **`bool | None`**（tri-state）：

| mcp 侧 `readOnlyHint` 值 | 语义 | HeAgent `ToolAnnotations.readOnlyHint` |
| --- | --- | --- |
| `True` | server 声明只读 | `True` |
| `False` | server 声明非只读 | `False` |
| `None`（缺省） | server 未声明 | `False` |

AC 明定 HeAgent 模型字段「均默认 `False`」（纯 `bool`，非 `bool | None`）。故 mapping 须把 tri-state 折叠为 bool：**`bool(ann.readOnlyHint)`** —— `bool(True)=True`、`bool(False)=False`、`bool(None)=False`，三态正确收敛。四字段同理。

> **不要**把 HeAgent 字段设计成 `bool | None`——那会让「server 未声明某 hint」与「server 声明 False」在数据层无法区分，且违背 AC「均默认 False」。fail-safe 的「缺信号」判定**不**靠字段内 None，而是靠 `ToolSchema.annotations is None`（schema 层），见下条。

### fail-safe 信号载体（数据层只负责正确表示，不裁决）

- **「工具缺 annotations」= `ToolSchema.annotations is None`**（schema 层的 None，**不是**字段内 None）。
- mapping 对 `tool.annotations is None` → 显式产出 `annotations=None`；对 present 的 annotations → 产出 `ToolAnnotations`（四 bool）。
- 谁是 None / 谁是 MCP 工具的判定（`_is_mcp_tool` + fail-safe）是 **14-2** 的事。本 story 只保证：**数据正确表示**「server 声明了什么」与「server 什么都没声明」。

### 零回归证明（SM-4 生命线，本 story 必须不退步）

`ToolSchema` 全仓仅 **2 个构造点**（已 grep 核实）：

1. `src/heagent/tools/decorator.py:93` —— `@tool` 装饰器，生成 19 个内置工具的 schema：`ToolSchema(name=..., description=..., parameters=...)`，**不传 annotations** → 新字段默认 `None` → 内置工具行为零变化。
2. `src/heagent/tools/mcp/mapping.py:42` —— 本 story 唯一修改点。

→ 新增字段是**可选 + 默认 None**，构造点 #1 零改动即兼容。既有 `tests/test_types.py`、`tests/test_mcp_mapping.py` 全部既有断言不触及 annotations，必然继续通过。**这是结构性零回归，不需额外护网。**

### 文件落点（全是 UPDATE，无 NEW 文件）

| 文件 | 动作 | 改动 |
| --- | --- | --- |
| `src/heagent/types.py` | UPDATE | +`ToolAnnotations` class（ToolSchema 之前或之后，紧邻合理）；`ToolSchema` +`annotations` 字段 |
| `src/heagent/tools/mcp/mapping.py` | UPDATE | `mcp_tool_to_schema` 内补 annotations 透传分支 |
| `tests/test_types.py` | UPDATE | +ToolAnnotations / ToolSchema.annotations 用例 |
| `tests/test_mcp_mapping.py` | UPDATE | +透传 / None / title 丢弃 / tri-state 折叠用例 |

### Anti-Patterns（勿犯）

- ❌ 在 `types.py` 写 `from mcp.types import ToolAnnotations`（破坏 DAG，types 上浮 mcp 依赖）—— 须手写 HeAgent 自有 4-bool 模型。
- ❌ 给 HeAgent `ToolAnnotations` 加 `title` 字段（AC 明定丢弃）。
- ❌ 把字段设计成 `bool | None`（违背 AC「均默认 False」，且让 fail-safe 判定歧义）。
- ❌ 在 `mapping.py` 用 `tool.annotations.readOnlyHint` 直接赋给 bool 字段而不折叠（Pydantic v2 会拒绝 None → 报错；须 `bool(...)`）。
- ❌ 越界改 `policy.py` / `tool_execution.py` / `engine/`（那是 14-2）。
- ❌ 在本 story 加任何「读 annotations 做裁决」的逻辑（数据层只透传，不裁决）。
- ❌ 改既有 3 字段（`name`/`description`/`parameters`）的映射行为或 docstring 风格（Surgical Changes——只加，不改既有）。

### Project Structure Notes

- 与既有结构完全对齐：`types.py` 是叶子模块（仅 import `enum.StrEnum`/`typing.Literal`/`pydantic.BaseModel`），新增 `ToolAnnotations` 同为叶子 Pydantic 模型，不引入任何内部 import。
- `mapping.py` 已 `from mcp.types import ... Tool` 等，新增透传逻辑复用既有 import（`Tool.annotations` 即 `mcp.types.ToolAnnotations | None`，无需新增 import）。
- 命名：类名 `ToolAnnotations`（PascalCase，不加后缀，遵 PEP 8 项目规范）；字段 `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`（camelCase，**与 mcp SDK 字段名一致**以便 mapping 直观映射——这是数据透传场景下唯一合理选择，非命名规范违规）。

### Testing Standards

- 框架：pytest + pytest-asyncio（auto 模式）。本 story 测试**全同步**（无 async、无 provider、无网络），验证「确定性数据映射」本质。
- 每个 test 文件若涉及 Settings 单例须 `reset_settings()`——本 story 测试不触 Settings，无需。
- 测试须捕捉**逻辑本质失效**：tri-state 折叠错（None 透传成 None 而非 False）、title 泄漏进 HeAgent 模型、缺省非 None 等。参见 Task 3 清单。

### Stack（不新增依赖）

- Python 3.11+ / Pydantic v2 / `mcp`>=1.28,<2（已由 V1 引入，本 story 不新增运行时依赖）。`mcp.types.ToolAnnotations` 字段已核实：`title`/`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`（均 `bool|None` 或 `str|None`）+ `model_config = ConfigDict(extra="allow")`。

### References

- [Source: `_bmad-output/mcp-client-v2/epics.md`#Story A.1] —— AC verbatim 来源
- [Source: `_bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md`#AD-1] —— annotations 经 ToolSchema 注入
- [Source: `_bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md`#Consistency Conventions] —— 数据模型约定（丢 title、四 hint、None 语义）
- [Source: `_bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md`#Inherited Invariants] —— DAG（types 不上浮 mcp）
- [Source: `src/heagent/types.py:94`] —— `ToolSchema` 现状（3 字段）
- [Source: `src/heagent/tools/mcp/mapping.py:39`] —— `mcp_tool_to_schema` 现状
- [Source: `src/heagent/tools/decorator.py:93`] —— 内置工具 ToolSchema 构造点（零回归证明）
- [Source: `src/heagent/tools/registry.py:62`] —— `get_schema()`（14-2 下游消费者，本 story 不动）
- 下游 story：`14-2-policy-annotation-gate`（AD-1 schema kwarg + AD-2 裁决 + AD-3 确定性）

## Dev Agent Record

### Agent Model Used

glm-5.2（Claude Code CLI，2026-07-17）

### Debug Log References

- TDD RED：首轮 `test_tool_annotations_has_no_title_field` 用 `pytest.raises(ValidationError)` 断言 title 被拒，失败——Pydantic v2 默认 `extra="ignore"`（静默丢弃，不报错）。判定为**测试假设错**（非实现错）：模型确实无 title 字段（`hasattr` 已满足「丢弃」）。修正测试为断言「字段不残留」，并清理随之变孤儿的 `import pytest` / `from pydantic import ValidationError`。
- ruff I001：补 `ToolAnnotations as McpToolAnnotations` 后 import 块需重排，`ruff check --fix` 自动 organize（aliased import 拆为独立 `from mcp.types import` 块，ruff 确定性输出）。

### Completion Notes List

- **AC-1 满足**：`types.py` 新增 HeAgent 自有 `ToolAnnotations(BaseModel)`（四 hint 纯 `bool` 默认 `False`，无 `title`，**零 mcp 导入**保 DAG）+ `ToolSchema.annotations: ToolAnnotations | None = None`（可选缺省 None）。`decorator.py:93` 内置工具构造点零改动 → 结构性零回归。
- **AC-2 满足**：`mapping.mcp_tool_to_schema` 经新增 `_mcp_annotations_to_heagent` 透传——`tool.annotations is None` → `schema.annotations=None`（fail-safe 信号载体，schema 层 None）；present → 四 hint `bool(ann.X)` 折叠。
- **AC-3 满足**：`idempotentHint`/`openWorldHint` 透传存储（V2 不裁决，交 14-2）。
- **tri-state 折叠**：mcp `bool|None`（True/False/None）经 `bool()` 收敛为 HeAgent 纯 `bool`（True/False/False）。
- **边界守住**：未触碰 `policy.py`/`tool_execution.py`/`engine/`（14-2 范围）；数据层先行，`annotations` 已就位但暂无消费者（设计预期）。
- **验证全绿**：`pytest` 549 passed（零回归）/ `mypy src` Success（62 files）/ `ruff check` All checks passed。新增 11 个测试用例（test_types +5 / test_mcp_mapping +6）。

### File List

- `src/heagent/types.py`（UPDATE：+`ToolAnnotations` 模型 + `ToolSchema.annotations` 字段）
- `src/heagent/tools/mcp/mapping.py`（UPDATE：+`_mcp_annotations_to_heagent` helper + `mcp_tool_to_schema` 透传 + import `ToolAnnotations`/`McpToolAnnotations`）
- `tests/test_types.py`（UPDATE：+`ToolAnnotations`/`ToolSchema.annotations` 5 个用例 + import）
- `tests/test_mcp_mapping.py`（UPDATE：+annotations 透传 6 个用例 + `McpToolAnnotations` import）

## Change Log

- 2026-07-17：Story 14-1 实现完成——annotations 数据管线落地（ToolAnnotations 模型 + ToolSchema.annotations + mapping 透传 + tri-state 折叠 + title 丢弃）。TDD red-green，全量回归零退步。Status → review。
