---
title: 'Story 67.5 支持系统 keyring 密钥存储'
type: feature
ticket: 5
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
  - 'src/heagent/config/keyring_store.py'
  - 'src/heagent/config/__init__.py'
  - 'tests/test_keyring_store.py'
---

## Intent

密钥只能经环境变量 / `.env` 提供；票面要求「支持环境变量与 keyring 两种存储方式，可配置启用」。

**Approach：** `config/keyring_store.py` 提供 `get_secret(name)`：`KEYRING_ENABLED=true` 时先查
系统 keyring（`keyring` 为可选依赖，缺失即显性说明并回退），命中即用；未命中回退环境变量/`.env`。
密钥解析收敛到一个函数，provider 装配与 MCP 凭据读取都走它。

## Verify

- `KEYRING_ENABLED=false`（默认）行为与现状完全一致（环境变量优先，有测试钉死）；
- 启用后 keyring 命中值生效、未命中回退环境变量；
- `keyring` 未安装时给一次显性 WARNING（含安装提示），不抛错、不静默；
- keyring 里的值不进日志/审计（脱敏口径与现有一致）。

## Boundaries

- 不把 keyring 变成硬依赖（可选 extra）。
- 不实现密钥写入 keyring 的 CLI（只做读取）。

## Implementation（实测）

- 落点：`config/keyring_store.py::get_secret`（`KEYRING_ENABLED=true` 时先查系统 keyring，未命中回退字段值；
  缺 `keyring` 包时告警一次并回退）、`Settings.secret()` 作为**唯一收敛点**、`providers/composition.py` 走它；
  `KEYRING_ENABLED` 默认 false，且进 `EXCLUSION_GROUPS.credentials`（网页控制台不可远程改）。
- 实测：`pytest tests/test_keyring_store.py -q` → 17 例全绿（默认路径与现状一致、keyring 命中、回退、缺包告警）；
  `mypy src` 对可选依赖加 `[[tool.mypy.overrides]] module=["keyring"]`。
