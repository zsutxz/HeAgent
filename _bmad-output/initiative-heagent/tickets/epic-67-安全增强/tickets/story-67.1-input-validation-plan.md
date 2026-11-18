---
title: 'Story 67.1 设计统一输入验证框架'
type: feature
ticket: 1
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
  - 'src/heagent/pub/validation.py'
  - 'tests/test_input_validation.py'
---

## Intent

用户输入目前分散在各入口自行检查（HTTP 请求体由 pydantic 校验、CLI 参数由 click 校验、
配置写入由 `config/catalog/guards.py` 的字段守卫校验），**失败形状与自定义规则能力各不相同**。
本 story 在 `pub/` 层建一个零依赖的最小框架：

- `Rule`（必填 / 类型 / 长度 / 正则 / 枚举 / 自定义 callable）与 `validate(data, fields)`；
- 失败返回结构化 `ValidationIssue(field, rule, message)` 列表 + 统一 `InputValidationError`
  （message 里逐字段列出问题，供 CLI/HTTP 直接展示）；
- 自定义规则通过 callable 注入，不需要改框架。

## Verify

- 框架单测覆盖：必填缺失、类型不符、超长、正则不匹配、枚举越界、自定义规则失败，逐项返回
  带字段名与规则的清晰 message；
- 至少一个真实入口接入（HTTP 请求体或配置写入），接入前后对外错误形状有测试钉死；
- 通过/失败都在同一入口判定，不存在「框架之外的第二套校验」。

## Boundaries

- 不替换 pydantic 模型校验（框架只补「跨字段/业务级规则」，不重造类型系统）。
- 不引入新依赖。
- 不改 `network/` 的依赖边界（`pub/` 是 network 唯一可用的本仓层）。

## Implementation（实测）

- 落点：`pub/validation.py`（`Rule` + `collect_issues` / `validate` / `InputValidationError`，零 heagent 依赖，
  只 stdlib + pydantic + 同层 `pub.exceptions`）；接入点选 `config/write.py::guard_reason`——它是仓库里唯一
  非 pydantic 的手写校验面（枚举 / 上下界 / 空值），另两个候选要么本身就是 pydantic 校验、要么无运行期判定点。
- 行为等价：`guard_reason` 只把守卫翻译成规则链，判定由框架做；对外仍是 `ConfigWriteRejection(INVALID_VALUE, "KEY: 原因")`。
- 实测：`pytest tests/test_input_validation.py tests/test_config_write.py -q` → 156 passed；
  接入面扩到 413 例（config/cli/credential 相关）全绿；`pub/validation.py` 覆盖率 100%。
