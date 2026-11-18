---
title: 'Story 67.9 审查并精简依赖'
type: feature
ticket: 9
created: '2026-11-18'
status: done
baseline_revision: '0b1b156'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'pyproject.toml'
  - 'src/heagent/tools/mcp/__init__.py'
---

## Intent

核心 `dependencies` 有 7 项。逐项核用途：`pydantic` / `pydantic-settings` / `click` / `httpx` /
`openai` / `anthropic` / `mcp`。其中 `mcp` 只服务可选能力（MCP 桥接），而 66.5 已让 provider SDK
延迟导入。

**Approach：** 把 `mcp` 从核心依赖移到可选 extra（`mcp` 组），核心 7 → 6（-14%）；MCP 子包改为
构造期导入并在缺依赖时给安装诊断（`pip install heagent[mcp]`）。`dev` extra 保持含 mcp，测试与
CI 不降级。

## Verify

- `pyproject.toml` 的 `dependencies` 为 6 项，`[mcp]` extra 存在；`dev` 包含它；
- 缺 `mcp` 时 `import heagent` 与 `heagent "hi"` 正常，MCP 相关子命令/工具给显性安装提示；
- `pytest tests/ -q -k mcp` 全绿；CI 安装行不变（dev 覆盖）。

## Boundaries

- 不动 `openai` / `anthropic`（主用途依赖，移出会破坏默认安装可用性）。
- 不删除 `httpx`（代码直接 import，属真实直接依赖）。

## Implementation（实测）

- 落点：`mcp` 从 core `dependencies` 移到 `[mcp]` extra（core 7 → 6，**-14.3%**），`dev` extras 含它；
  `tools/mcp/` 的 SDK 导入收敛到新 `tools/mcp/sdk.py`（构造期导入 + 缺包时给 `pip install heagent[mcp]` 诊断）。
- 实测：`import heagent` 与 `import heagent.tools.mcp` 后 `mcp` **不在** `sys.modules`；
  `pytest -q -k mcp` 全绿；CI 安装行不变（dev 覆盖）。
