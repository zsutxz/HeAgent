---
title: 'Story 72.3 自检与排障面（doctor + 启动公告 + 排障指引）'
type: feature
ticket: 3
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
  - 'src/heagent/cli/doctor.py'
  - 'src/heagent/network/ws_host.py'
  - 'src/heagent/cli/http.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** `lan` 档的三条准入只在装配期抛异常，用户看不到「哪一条不合规、该改成什么」；
启动公告只有 `listener=local|external`，`lan` 无从辨认；`9301` / `WS_EXTERNAL_*` 的老排障文案
（403、10061）指向已退役的配置。

**Approach:** 三条准入做成 `doctor` 的独立 findings（各带改法）+ 启动期 preflight 同名判据（同一口径）；
启动公告按 `mode` 三档分叉，`lan` 额外写明 `auth=none` 与 cron 推送可见性；排障文案改指新键。

## Boundaries & Constraints

**Always:**
- `doctor` 与启动 preflight 同口径（同一组合两种入口给同一结论），但**职责不重叠**：doctor 全量体检、preflight 只阻断。
- `lan` 的三条准入各自成一条 finding（code + message + fix），不合并成一句「配置非法」。
- 启动日志每次启动**恰一条** `listener=lan auth=none`（`caplog` 计数断言，不是「存在」）。

**Never:**
- 不在 `lan` 合法时误报「缺 token」（`main_external` 必须排除 `ws_lan_no_auth`）。
- 不把 `lan` 的告警降成 INFO（它描述的是「同网段可驱使代理」）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| LAN_OK | 私有 IPv4 + 开关 | 零 ERROR；启动一条 `listener=lan auth=none` WARNING | — |
| LAN_LOOPBACK | 回环 + 开关 | `doctor.ws_lan_loopback` ERROR + fix「drop WS_LAN_NO_AUTH」 | 启动 preflight 同样阻断 |
| LAN_WILDCARD | `0.0.0.0` + 开关 | `doctor.ws_lan_host_not_private` ERROR + 查 IP 的改法 | 同上 |
| LAN_CONFLICT | 与 `WS_LOCAL_AUTH_ENABLED` 同开 | `doctor.ws_lan_auth_conflict` ERROR | 同上 |
| RETIRED_ENV | 老 `.env` 含 `WS_EXTERNAL_*` | 仅 `doctor.retired_key` INFO，不阻断 | 不进 `env_unknown_keys` |

</intent-contract>

## Code Map

- `src/heagent/cli/doctor.py` — `_lan_mode_findings()` 三条（`ws_lan_auth_conflict` / `ws_lan_loopback` / `ws_lan_host_not_private`）；`main_external` 排除 `ws_lan_no_auth`；缺 token 文案改成「要么 token、要么显式豁免」。
- `src/heagent/network/ws_host.py` — `ws event=exposed host=… listener=lan auth=none tls=… cron_push=…` WARNING；`auth_token_ignored` 的 `reason` 分 `lan_no_auth` / `loopback_bind`。
- `src/heagent/cli/http.py` — `_announce_ws_listeners()`：`lan` 档 stderr 公告写明「NO authentication」与代价。
- `docs/faq.md` / `docs/errors.md` — `9301` / `WS_EXTERNAL_*` 处置改为 `WS_LAN_NO_AUTH` 三档表 + `10061` / `403` 判据；启动校验从 6 项表里换掉 `ws_external_binding` → `ws_lan_no_auth`。
- `scripts/ws_manual_probe.py` — 示例从 `9301 + --token` 换成 `9201`（`--token` 只在 `external` 档需要）。

## Evidence

- `pytest tests/test_cli_doctor.py` → 33 passed（含 4 条新增 lan 用例）。
- 真实启动取证（容器私网 `172.17.0.3`）：日志恰一条 `ws event=exposed … listener=lan auth=none tls=ws cron_push=off`，
  同时 `[ws] WARNING: exposed on 172.17.0.3:9201 (lan mode; NO authentication; PLAINTEXT); any device on this
  network can drive the agent`。
