---
title: 'Story 67.7 编写 HTTP/WS 端点安全测试'
type: feature
ticket: 7
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
  - 'tests/network/test_endpoint_security.py'
  - 'tests/contract_baselines/transport_routes.json'
---

## Intent

端点安全口径散落在多个测试文件（`test_http_security.py` / `tests/network/test_ws_*`），
没有「每个对外端点都有认证/授权/输入验证用例」的可执行判据。

**Approach：** 新增 `tests/network/test_endpoint_security.py`：以 `tests/contract_baselines/transport_routes.json`
的路由集合为真源，断言每条路由都在覆盖表里，并对每条路由跑三类用例（未认证、越权/只读方法、
畸形输入）。覆盖表与基线集合**相等**（新增路由漏测即红）。

## Verify

- 覆盖表 ⊇ 基线路由集合（相等断言，缺一即红）；
- 未认证访问受保护路由被拒（401/403）；畸形 JSON / 超长字段被拒且错误形状统一；
- `pytest tests/network -q` 全绿；现有安全测试不删不减。

## Boundaries

- 只加测试与覆盖表，不改端点实现（发现真缺陷只登记，不在本 story 修）。
- 不引入 fuzz 框架或新依赖。

## Implementation（实测）

- 落点：`tests/network/test_endpoint_security.py`（11 例）。覆盖表以 `tests/fixtures/contract_baselines/transport_routes.json`
  的路由集合为真源，集合相等断言钉住「新增路由漏测即红」。
- 三类用例：Host 伪装（403 `origin_forbidden`）、写闸门 / 只读方法面（405）、畸形输入（坏 JSON / 超长字段 / 空 prompt，
  且断言拒绝发生在 handler 调用之前）；WS 侧按真实认证门（1008 close）与只读路由可见性分别测。
- 实测：`pytest tests/network/test_endpoint_security.py -q` → 11 passed；`pytest tests/network -q` 既有用例不红。
