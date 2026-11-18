---
title: 'Story 63.6 提取常用 fixture 到 conftest.py'
type: test
ticket: 6
created: '2026-11-18'
status: built
baseline_revision: 'cab4552'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'tests/conftest.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 82 个 fixture 散布各测试文件，同名重复定义 21 处（4 个名字族 +
`fresh_registry`）：settings 单例重置族以三种命名（`clean_settings` /
`_clean_settings` / `_reset_settings` / `_reset_settings_singleton`）重复 13 处、
`workspace_dir` ×4（仅路径前缀差一字符串）、`successful_step` ×4（goal 族逐字
同源）、`fresh_registry` ×2。

**Verify：≥10 个可复用 fixture 收敛至 tests/conftest.py，测试文件改为复用而非
重复定义，全量测试通过。**

## Design

conftest.py 新增 4 个 canonical fixture（`clean_settings` / `workspace_dir` /
`fresh_registry` / `successful_step`），21 处重复定义删除后按名解析到 conftest：

- **autouse 语义保持**：9 个 autouse 文件删本地定义后补模块级
  `pytestmark = pytest.mark.usefixtures("clean_settings")`（等价于原 per-file
  autouse）；其中 8 个文件的旧名不在 conftest 集合，脚本删除后断言旧名零残留
  才落盘（有残留即回滚该文件）。
- **参数注入文件（12 处）零改名**：参数名与 conftest fixture 同名，删除本地
  定义后自动解析到 conftest。
- `workspace_dir` 统一路径前缀为 `ws-`（勘测确认四个消费文件均不断言前缀字符串）。
- 一次性脚本（Temp 区，不入库）按精确块删除执行：装饰器行起、首个列 0 非空行止；
  `test_sandbox_mode.py` 勘测误报 `fresh_registry`（实为 `test_safe_logging.py`），
  以全库 grep 纠正后处理。

**统计（两个口径均满足 verify）**：删除重复定义 21 处；conftest fixture 总数
6 → 10。

## Outcome

- 受影响 19 文件 + conftest：ruff check / format 全绿（顺带修
  `test_safe_logging.py` 的 TC001——fixture 删除后 `ToolRegistry` 降级为仅注解
  使用，迁 TYPE_CHECKING 块）。
- 受影响测试面 664 passed / 1 skipped；全量回归结论见提交附注。

</frozen-after-approval>
