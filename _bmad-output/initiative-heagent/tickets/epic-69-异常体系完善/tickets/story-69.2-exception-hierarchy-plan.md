---
title: 'Story 69.2 建立异常层次结构'
type: chore
ticket: 2
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

所有异常都直接继承 `HeAgentError`，没有「分类」层，调用方只能逐类 catch，无法 `except` 一整类。

**Approach：** 在基类与具体异常之间插入分类层（`ProviderError`/`ToolError`/`EngineError`/`AgentError`/
`SessionError`/`ConfigurationError` 作为二级基类），具体异常挂到对应分类下；
`HeAgentException` 作为 `HeAgentError` 的**兼容别名**（票面措辞），`__all__` 一并导出。

## Verify

- `issubclass(每个异常, HeAgentException)` 全部成立（测试遍历 `pub.exceptions` 全部类断言）；
- 每个具体异常恰有一个分类祖先，分类层本身可直接 catch（`except ToolError` 捕获全部工具异常）；
- 层次表由测试断言（不靠文档口头约定），新增异常漏挂分类即红。

## Boundaries

- 不改任何现有类的名字；`HeAgentException` 只是别名，不是第二个基类。
- 不引入 `__init_subclass__` 魔法来强制分类（显式继承即可读）。

## Implementation（实测）

- 层次：`HeAgentError` → 分类（`ProviderError` / `ToolError` / `EngineError` / `AgentError` / `SessionError` /
  `ConfigurationError`）→ 具体异常，共 26 个类；`HeAgentException = HeAgentError` 是**别名**（不是第二个基类）。
- 判据：每个具体异常恰有一个分类祖先（测试遍历断言）；`except <分类>` 覆盖整类（4 条 catch 判据）。
- 实测：`pytest tests/test_exceptions.py -q` → 21 passed；`scripts/contract_snapshot.py --check` 四份基线全绿。
