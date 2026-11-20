---
title: 'Story 72.5 落地与端到端验收'
type: feature
ticket: 5
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
  - '.env'
warnings: ['.env 属本地运行配置（gitignore），改动需宿主重启进程生效；宿主真机 netstat 对账由用户侧执行']
deferred: []
---

<intent-contract>

## Intent

**Problem:** 代码就绪不等于第一步生效：本机 `.env` 仍绑回环、仍挂第二 listener（`9301`）、仍启 wss ⇒
客户端连 `ws://192.168.2.226:9201` 依然 10061 / 403。

**Approach:** `.env` 落成第一步形态（`WS_HOST=192.168.2.226` + `WS_LAN_NO_AUTH=true`、删退役键、注释掉 TLS），
并在容器内用**私有网卡地址**跑同一套判据（绑定面 / 无 token 握手 / 提交通道 / 状态面 / 启动公告）。

## Boundaries & Constraints

**Always:**
- 只改 `.env`（本地运行配置），不改任何已跟踪文件；改动前留备份。
- 判据必须是可复制的命令 + 原始输出；宿主真机部分若不在容器能力内，**标未实测**并给用户可执行的命令。
- 回滚判据同时给：改回 `WS_HOST=127.0.0.1` + 删开关即回到本地模式。

**Never:**
- 不用设计推断冒充实测。
- 不把 `.env` 的改动提交进版本库（gitignore 已覆盖，需在报告里注明）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| BIND_INTRA | `.env` 第一步形态 | `netstat` 仅 `<私有 IPv4>:9201`；`127.0.0.1:9201` 拒绝 | — |
| NO_9301 | 同上 | `9301` 无监听 | — |
| TOKENLESS | 无 `Authorization` 握手 | hello + `ack`（ping） | 失败即 403/1008 |
| STATUS | `GET /api/status` | ws listener `mode=lan`、`tls=false` | — |
| ROLLBACK | 改回回环 + 删开关 | 回到 `local`，日志不再出现 `listener=lan` | — |

</intent-contract>

## Code Map

- `.env`（本地、gitignore）：`WS_HOST=192.168.2.226`、新增 `WS_LAN_NO_AUTH=true`；
  删 `WS_EXTERNAL_HOST` / `WS_EXTERNAL_PORT`；`WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE` 注释掉（第一步明文，第二步恢复）。
- 备份：`.heagent/tmp/out/env.backup`。

## Evidence（容器内，以私网 `172.17.0.3` 代替 `192.168.2.226`）

```text
127.0.0.1:9201 -> REFUSED(errno=111)
172.17.0.3:9201 -> OPEN
172.17.0.3:9301 -> REFUSED(errno=111)

ws_manual_probe ws://172.17.0.3:9201 ping
  <- {"type":"hello","version":"0.10.0"}      PASS hello 首帧
  -> {"command":"ping"}
  <- {"type":"ack","command":"ping","run_id":""}  PASS 集合端点 ack

GET /api/status listeners:
  [('http','127.0.0.1',9101,'local',False), ('ws','172.17.0.3',9201,'lan',False)]

日志:
  ws event=started address=172.17.0.3:9201 listener=lan tls=ws
  ws event=exposed host=172.17.0.3 listener=lan auth=none tls=ws cron_push=off hint=...
```

配置面校验（读改后的 `.env`）：`build_ws_server_config()` → `mode=lan`、`requires_auth=False`、
`tls_enabled=False`、`port=9201`；`validate_startup()` 只剩 `provider_credentials`（本机 `.env` 无 provider 凭据，
与本次改动无关，改前同状）。

**未实测（需宿主真机）**：`netstat -ano | findstr :9201` 的本地地址是否为 `192.168.2.226`；
客户端 `ws://192.168.2.226:9201` 的三处对账。容器内无该网卡地址，故以私网地址做同型判据。
