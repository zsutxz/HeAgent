---
title: 'Story 72.1 局域网免认证监听模式（lan）'
type: feature
ticket: 1
created: '2026-11-19'
status: done
baseline_revision: '9eb9410'
route: full
route_source: auto
risk: high
review: thorough
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'src/heagent/network/ws_host.py'
  - 'src/heagent/network/exposure.py'
  - 'src/heagent/config/validation.py'
  - 'src/heagent/cli/http_config.py'
  - 'src/heagent/cli/doctor.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** `docs/tls-connect-guide.md` 第一步要「`9201` 绑私有 IPv4 + 明文 + 不设 token」，但今天
非回环绑定一律落 `external` 模式（`requires_auth` ⇒ 缺 token 拒绝构造），这个组合压根起不来；而
绕过它的唯一出口 `WS_EXTERNAL_HOST` 又要求 token + 双监听并存，与第一步形态冲突。

**Approach:** 新增第三档监听身份 `lan`：非回环绑定 + 显式 `WS_LAN_NO_AUTH=true` ⇒ 免认证，但三条准入
（私有地址字面量 / 与 `WS_LOCAL_AUTH_ENABLED` 互斥 / 回环上无意义）与每次启动一条 WARNING 兜底；
Host/Origin 防线**保留**（只有 `external` 走「防线替换」）。

## Boundaries & Constraints

**Always:**
- 默认形态零改动：回环绑定仍 `local` + 免 token + 旁路照挂。
- 不开 `WS_LAN_NO_AUTH` 时非回环仍 fail-closed，错误消息点名两个改法（token / 内网免认证）。
- 私有地址判定单点在 `network/exposure.py`；`config/validation.py` 内联等价实现，跨层等价由判据钉住。
- 免认证 listener 每次启动**恰一条** WARNING，写清「谁能连」与「cron 推送可见性」。

**Never:**
- 不把 `WS_LAN_NO_AUTH` 默认打开，不为兼容保留别名。
- 不在 `lan` 模式挂 `/api/cli/ws`（终端内容不外溢的 D9 不变量）。
- 不引入「允许哪些客户端 IP」的白名单（无认证就是无认证）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| LOOPBACK_DEFAULT | `WS_HOST=127.0.0.1` | `mode=local`、免 token | 无 |
| LAN_OK | 私有 IPv4 + `WS_LAN_NO_AUTH=true` | `mode=lan`、无 token 握手 `101`、ping 得 ack | 无 |
| LAN_NO_FLAG | 私有 IPv4、开关关 | 构造即拒 | `WsConfigError` 点名 `WS_AUTH_TOKEN` / `WS_LAN_NO_AUTH` |
| WILDCARD | `0.0.0.0` / `::` + 开关开 | 拒绝启动 | 消息点名「需要私有地址字面量」 |
| PUBLIC | 公网 IPv4 / 主机名 + 开关开 | 拒绝启动 | 同上（不解析 DNS） |
| AUTH_CONFLICT | 开关与 `WS_LOCAL_AUTH_ENABLED` 同开 | 拒绝启动 | 消息点名互斥 |
| LOOPBACK_FLAG | 回环 + 开关开 | 拒绝启动 | 消息说明「回环本就免认证」 |
| HOST_SPOOF | `lan` listener + `Host: evil.example` | accept 前拒绝（`origin_rejected`） | close 1008 |

</intent-contract>

## Code Map

- `src/heagent/network/exposure.py` — 新增 `is_private_address()`（IP 字面量 + private/link-local；通配/公网/回环/CGNAT/主机名一律假），登记 `__all__`。
- `src/heagent/network/ws_host.py` — `WsServerConfig.lan_no_auth`；`mode` 三值；`requires_auth` 只认 `external`（或回环 + `local_auth`）；`_validate_auth_and_tls` 三条准入；`auth_token_ignored` 的 reason 分档；新增 `listener=lan auth=none` 暴露 WARNING；模块/类 docstring 同步。
- `src/heagent/network/http_protocol.py` — `ListenerMode.LAN`。
- `src/heagent/config/__init__.py` — `ws_lan_no_auth`（默认 False）。
- `src/heagent/config/validation.py` — `REQUIRED_SETTING_KEYS` 加键；`_is_private_address` 内联实现；`_gate_ws_auth` / `_judge_ws_auth_token` 排除 `lan`；新增 `ws_lan_no_auth` 检查（gate/judge/options）。
- `src/heagent/cli/http_config.py` — 接线 `lan_no_auth`；旁路跳过告警改 `reason=non_loopback_listener` + `listener=<mode>`。
- `src/heagent/cli/doctor.py` — `main_external` 排除 `ws_lan_no_auth`（不在合法内网配置上报「缺 token」）。
- `tests/test_ws_lan_mode.py` — 新增 30 例（准入白名单 / 跨层等价 / 配置组合 / 装配层 / 预检 / 真实 TCP / Host 防线 / 旁路不挂）。
- `tests/test_security_posture_contract.py` — 谓词分组登记 `ws_lan_no_auth`（默认关 = 安全侧）。

## Evidence

- `pytest tests/test_ws_lan_mode.py tests/network tests/test_cli_http.py tests/test_cli_doctor.py tests/test_config_validation.py tests/test_security_posture_contract.py tests/test_architecture_contracts.py tests/test_http_status_api.py -q` → 960 passed。
- `ruff check src tests` 全绿；`ruff format --check` 515 files；`mypy src` no issues（233 files）。
- 真实 TCP：容器私网地址 `172.17.0.3:<随机口>` 上 `ws://…/api/runs/ws` 无 token 发 `{"command":"ping"}` 得 `{"type":"ack","command":"ping","run_id":""}`；同 listener 上 `Host: evil.example` 被 `origin_rejected / host not allowed` 拒。
