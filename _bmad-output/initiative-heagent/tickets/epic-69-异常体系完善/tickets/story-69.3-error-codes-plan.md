---
title: 'Story 69.3 设计并实现统一错误码体系'
type: chore
ticket: 3
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
  - 'docs/errors.md'
---

## Intent

异常没有错误码，`docs/errors.md` 是给人看的散文索引；程序侧无法稳定按码分支（`HttpErrorCode` 只覆盖传输层）。

**Approach：** `pub/exceptions.py` 给每个异常类加 `code: ClassVar[str]`（形如 `E_PROVIDER_RATE_LIMIT`），
实例经 `.code` 读取；`error_catalog()` 返回 `code → (类, 描述, 建议操作)` 映射，`docs/errors.md` 的错误码节
由测试断言与代码**一致**（不手抄第二份）。

## Verify

- 每个异常类都有唯一 `code`（重复/缺失即红）；
- `error_catalog()` 可程序化解析（返回 Pydantic 模型，含码/类名/描述/建议）；
- `docs/errors.md` 的码表与 `error_catalog()` 逐条一致（测试解析文档表格比对）；
- 未知异常的 `error_code_of(exc)` 返回 `E_UNKNOWN`，不抛。

## Boundaries

- 不把 `HttpErrorCode` 合并进来（传输层错误码有独立契约与基线）。
- 错误码一旦发布不改名（只增不复用）。

## Implementation（实测）

- 每类带 `code: ClassVar[str]`（`E_<分类>_<具体>`）+ `description` / `suggestion`；实例经 `.code` 读取。
- `error_catalog()` 返回 Pydantic `ErrorCatalogEntry` 列表（码/类名/描述/建议，顺序 = 层次顺序）；
  `error_code_of(exc)` 对非框架异常返回 `E_UNKNOWN` 且不抛。
- `docs/errors.md` 第二节改为**错误码总表**（26 行），由测试解析该表与 `error_catalog()` 逐条比对
  （文档不手抄第二份事实）；覆盖口径数字同步（35 传输码 + 26 异常类 + 12 CLI 条 = 73）。
- 实测：`pytest tests/test_exceptions.py -q` → 21 passed；`mkdocs build --strict` 0 warning。
