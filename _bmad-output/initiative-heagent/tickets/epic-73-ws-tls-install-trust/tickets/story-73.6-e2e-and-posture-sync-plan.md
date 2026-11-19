---
title: 'Story 73.6 端到端验收与安全口径同步'
type: feature
ticket: 6
created: '2026-11-19'
status: ready-for-dev
baseline_revision: '7cc8baba'
route: full
route_source: auto
risk: medium
review: thorough
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'docs/frame.md'
  - 'AGENTS.md'
  - 'CLAUDE.md'
  - 'tests/test_security_posture_contract.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 第二步完成后，安全口径真源（`docs/frame.md` §4.19 要素 4/5）仍写着「非回环分 `lan` /
`external` 双档」，派生副本（AGENTS / CLAUDE）与守卫短语集也没有「加密 + token 是生产形态、
`lan` 是调试档」这条事实；同时没有任何端到端证据证明 wss + pin 真的通了。

**Approach:** 把口径三处（真源 / 派生 / 守卫短语集）同批改写，并按七项判据做端到端取证
（含一条 pin 不匹配的反向用例，证明校验真的生效）。

## Boundaries & Constraints

**Always:**
- 口径改写**不软化**两条：①「加密 + token 才算第二步完成」；②「`lan` 是显式调试档，每次启动一条 WARNING」。
- 要素数量与编号不变（1..6）、canonical 段只出现一次（既有守卫判据）。
- 反向判据必须留证：临时把客户端 pin 改错 ⇒ 握手被拒且错误码 `pin_mismatch`；改回后复测通过。
- `.env` 落地后 `WS_LAN_NO_AUTH` 的取值要写清「生产档关 / 调试档开」，不留模糊状态。
- 未在宿主真机跑过的项一律标 `未实测`，并列用户可执行命令（不含密钥回显）。

**Never:**
- 不改归档历史文档（`archive-v6/`、`epics/`、`retrospective-all-cycles.md` 正文）。
- 不在报告里粘贴 `ca.key` / `identity.key` / 完整 pin 之外的私钥材料。
- 不为通过守卫而删除短语（删短语必须使守卫红，作为反向证据记录下来）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| POSTURE_SYNC | frame §4.19 改写完成 | `test_security_posture_contract` 绿，要素仍 1..6 | 红则点名缺的短语 |
| POSTURE_REVERSE | 删掉任一关键短语 | 守卫红（留两次运行结果） | 记录后还原 |
| E2E_PIN_OK | 真实 wss + 正确 pin | 握手成功、提交 run、收到事件 | 无 |
| E2E_PIN_BAD | pin 改错 | 握手被拒、错误码 `pin_mismatch` | 显性错误 |
| E2E_EXPIRED | 过期夹具 | 拒绝、错误码 `cert_expired` | 显性错误 |
| DOCS_GATE | 改完 docs | `mkdocs build --strict` 0 warning | 告警即失败 |
| HOST_UNVERIFIED | 宿主不可达 | 报告标 `未实测` + 命令清单 | 不伪造实测 |

</intent-contract>

## Code Map

- `docs/frame.md` — §4.19 要素 4/5（三档 → 加密常态 + `lan` 调试档）、§4.17.1 监听模式表（`tls` 列与
  口令）、文首手写 TOC 行（改标题必同步）。
- `AGENTS.md`「⚠️ 安全声明」要素 4/5、`CLAUDE.md`「安全口径」— 同批改写，要素不增不删。
- `tests/test_security_posture_contract.py` — `FRAME_ELEMENT_PHRASES` / `AGENTS_ELEMENT_PHRASES` 更新
  （保留正向包含风格：`wss`、`Authorization: Bearer`、`pin`、`lan` 调试档）。
- `deploy/README.md` / `.env.example` / `CHANGELOG.md`（`### Added` / `### Changed`）— 同步。
- 验收报告落本 plan 的 `## Evidence`（命令 + 原始输出 + 未实测项清单）。

## Evidence（开工前取证，交付后回填）

- 已实测：`tests/test_security_posture_contract.py` 现守卫「要素 1..6、canonical 段唯一、短语齐全」，
  短语集为正向包含（`FRAME_ELEMENT_PHRASES` / `AGENTS_ELEMENT_PHRASES`）。
- 已实测（2026-11-19 补做 retro 时）：全量 `pytest` 5518 passed / 0 failed；六门全绿，可作本票基线对照。
