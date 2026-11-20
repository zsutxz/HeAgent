---
title: 'Story 72.4 安全口径 canonical 与派生副本同步'
type: feature
ticket: 4
created: '2026-11-19'
status: done
baseline_revision: '9eb9410'
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
warnings: ['需求文档 docs/tls-connect-guide.md 在会话中途从工作树消失，其「已实施」改写未能落盘']
deferred: []
---

<intent-contract>

## Intent

**Problem:** §4.19 要素 4 写的是「WS 绑非回环 ⇒ 强制 Bearer、缺 token 拒绝启动」，与新增的 `lan` 档直接冲突；
派生副本（`AGENTS.md` / `CLAUDE.md`）与守卫测试必须同批改，否则口径分裂或测试红。

**Approach:** 要素 4 从单档改写成两档（`external` 默认强制 token / `lan` 显式免认证，只接受私有地址字面量），
要素 3 补「`lan` 绑定 ≠ 同网段可信」，要素 5 端点可见性按三档重述；派生副本同步；守卫短语集加入
`WS_LAN_NO_AUTH`；§4.17.1 的表格行、§4.18 的 `ws_host` 行、§4.17 的自启动段一并改。

## Boundaries & Constraints

**Always:**
- 真源唯一：只在 `docs/frame.md` §4.19 承载论证，`AGENTS.md` 是派生副本（要素数 1..6 不变、不增删）。
- 「不倒退」：要素 4 必须同时保留 `Authorization: Bearer` / `fail-closed` / `浏览器 WebSocket API` 与新词 `WS_LAN_NO_AUTH`。
- 标题改动后同步 `docs/frame.md` 手写 TOC 行（`tests/test_docs_links.py` 是唯一机器守卫）。

**Never:**
- 不把 `lan` 写成「对外模式的一种」——它是**内网调试入口**，且明确不是边界。
- 不在派生副本里扩写论证。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| PHRASE_DROP | 删掉要素 4 的 `WS_LAN_NO_AUTH` | `test_frame_canonical_section_keeps_the_six_elements[frame-element-4]` 红 | 守卫点明缺哪个短语 |
| ELEMENT_COUNT | 合并/新增要素 | 要素号必须仍是 `[1..6]` | 红 |
| DUP_HEADING | 复制出第二份 canonical 段 | `test_canonical_heading_appears_exactly_once` 红 | 红 |
| TOC | 改小节标题 | 手写 TOC 行必须同改 | `test_docs_links` 红 |

</intent-contract>

## Code Map

- `docs/frame.md` — §4.19 要素 3/4/5；§4.17.1 引言 + 端点表（对外 listener 列 → `lan` / `external`）+ 监听模式（三档）+ 只读旁观 + 「单 listener 装配」；§4.17 自启动段；§4.18 的 `ws_enabled` / `ws_host` 两行；§4.17.1.2 通知流可见性。
- `AGENTS.md` — 「⚠️ 安全声明」要素 3/4/5 与落点提示。
- `CLAUDE.md` — 「安全口径」段。
- `deploy/README.md` — listener 表（2 条）+ 四种部署姿态（姿态 4 改成 `lan`）+ 配置约束 + 安全前置。
- `.env.example` — 删 `WS_EXTERNAL_*` 注释块、加 `WS_LAN_NO_AUTH` 块与退役说明。
- `CHANGELOG.md` — `## [Unreleased]` 增 `### Removed（破坏性）` + `### Added`（`lan` 模式）。
- `tests/test_security_posture_contract.py` — 两个短语集的要素 4 加 `WS_LAN_NO_AUTH`；删 `ws_external_*` 谓词分组；新增 `test_retired_external_listener_keys_stay_gone`。

## Evidence

- `pytest tests/test_security_posture_contract.py tests/test_docs_links.py` → 全绿（要素仍 1..6、canonical 段唯一）。
- `mkdocs build --strict` → 0 warning。
- `docs/tls-connect-guide.md`（需求真源）在会话中途消失，故其「服务端已实施」改写与 mkdocs nav 登记未落地；
  相关事实已写进 `deploy/README.md`（姿态 4）与 `.env.example`。
