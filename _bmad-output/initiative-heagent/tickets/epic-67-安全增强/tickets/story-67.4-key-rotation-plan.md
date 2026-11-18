---
title: 'Story 67.4 支持密钥轮换提醒'
type: feature
ticket: 4
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
  - 'src/heagent/config/rotation.py'
  - 'src/heagent/housekeeping.py'
  - 'tests/test_key_rotation.py'
---

## Intent

密钥来自 `.env` / `~/.heagent/setting.md`，没有「用了多久」的概念，也没有轮换提醒。

**Approach：** `config/rotation.py`：在密钥**首次被观测到**时把 `(key_name, first_seen)` 记进
`<项目状态根>/key_rotation.json`（之后不改写）；启动期（housekeeping fail-soft 调用）比对
`KEY_ROTATION_REMIND_DAYS`（默认 90，可配置），超期则 WARNING 列出密钥名、使用天数与建议操作。

## Verify

- 首次观测写入记录；第二次启动不重置 `first_seen`；
- 把 `first_seen` 改成 100 天前 ⇒ 启动日志出现含密钥名与天数的 WARNING；
- `KEY_ROTATION_REMIND_DAYS=0` 关闭提醒；
- 只记**密钥名**，从不记值（测试断言文件里没有明文密钥）。

## Boundaries

- 不改密钥读取优先级，不引入凭据管理器。
- 提醒只到日志（不阻塞启动、不失败）。

## Implementation（实测）

- 落点：`config/rotation.py`（`<项目状态根>/key_rotation.json` 记录每个密钥名首次观测日期，只写一次；
  `observe()` 返回 `recorded` / `overdue`）、`KEY_ROTATION_REMIND_DAYS`（默认 90，`ge=0`，0 关闭）、
  `housekeeping.py` 启动期 fail-soft 调用（只 WARNING，不阻塞启动）。
- 只记密钥名与日期，从不记值（测试断言状态文件里不含明文）。
- 实测：`pytest tests/test_key_rotation.py -q` → 18 例全绿（首次写入、二次不重置、100 天前触发 WARNING、0 关闭）。
