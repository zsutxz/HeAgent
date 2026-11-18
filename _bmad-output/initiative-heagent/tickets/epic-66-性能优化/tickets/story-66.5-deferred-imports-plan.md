---
title: 'Story 66.5 延迟导入大型依赖'
type: perf
ticket: 5
created: '2026-11-18'
status: done
baseline_revision: '0a70447'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/providers/openai.py'
  - 'src/heagent/providers/anthropic.py'
  - 'src/heagent/providers/responses.py'
  - 'src/heagent/providers/__init__.py'
  - 'tests/test_deferred_imports.py'
---

## Intent

`openai` 与 `anthropic` SDK 是启动期最重的两个第三方导入（各自的 pydantic/httpx 子图），而它们在
`openai.py` / `anthropic.py` / `responses.py` 的**模块顶层**被导入，`providers/__init__.py` 又
eagerly 导入这三个模块 ⇒ 只要 `import heagent`（或 CLI 启动）就把两个 SDK 全拉进来，与当前
`ACTIVE_PROVIDER` 无关。

**Approach：**

- 三个 provider 模块把 `from openai import AsyncOpenAI` / `from anthropic import AsyncAnthropic`
  移到构造函数（或首次调用）内；类型注解走 `TYPE_CHECKING` 导入；
- `providers/__init__.py` 用 PEP 562 `__getattr__` 懒导出（`__all__` 不变），
  `from heagent.providers import OpenAIProvider` 行为保持不变；
- 检查 `config/` / `cli/` 侧是否有顶层 `heagent.providers.*` 导入把 SDK 拉回来（有则一并延迟）。

## Verify

- `python -c "import heagent; import sys; print('openai' in sys.modules)"` → `False`，
  同理 `anthropic`；`from heagent.providers import OpenAIProvider` 仍可用（不 import SDK），
  实例化 `OpenAIProvider(...)` 时才 import。
- 冷启动对比：同一命令跑 5 次取最小值，`python -c "import heagent"` 耗时下降 >20%；
  判据以「SDK 不在 `sys.modules`」为主（时间只作旁证，CI 上不稳定）。
- `pytest tests/providers -q`、`pytest tests/test_cli.py -q` 全绿；`mypy src` 无新增错误。

## Boundaries

- 不改 provider 的公开构造签名与默认参数。
- 不把 SDK 变成可选依赖（仍是 `[dev]` 安装的一部分）。
- 不为延迟导入引入 `importlib.util.find_spec` 之类的探测分支。

## Implementation（实测）

- 落点：`providers/{openai,anthropic,responses}.py` 的 SDK 导入改为模块级 PEP 562 `__getattr__` 懒导入
  （保住 29 处 `@patch("heagent.providers.<mod>.AsyncXxx")` 缝），构造函数经 `sys.modules[__name__]` 取类；
  `providers/__init__.py` 改为 `_EXPORTS` 路由表 + `__getattr__`，`__all__` 逐字不变。
- 实测：`import heagent` 后 `openai` / `anthropic` 均不在 `sys.modules`（模块数 3324 → 366）；
  `from heagent.providers import OpenAIProvider` 仍不拉 SDK，实例化后才进 `sys.modules`。
  `pytest tests/providers tests/test_deferred_imports.py tests/test_architecture_contracts.py tests/test_cli.py -q`
  → 310 passed；`mypy src` → Success（223 files）。
- 冷启动：9p 挂载上抖动大，5 次最小值 before 13208 ms → after 1074 ms，仅作旁证（主判据是 `sys.modules`）。
