---
title: 'Story 73.6 端到端验收与安全口径同步'
type: feature
ticket: 6
created: '2026-11-19'
status: done
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

## Evidence（交付回填，2026-11-19）

### 口径同步

- `docs/frame.md` §4.19 要素 4 改写为「两档 + 生产形态 `wss` + token」：新增 `wss` / `SPKI-SHA256 pin` /
  `heagent tls rotate-key` 是唯一改 pin 的动作、`lan` 与 TLS 互斥；要素数量与编号仍 1..6。
- `AGENTS.md` 要素 4、`CLAUDE.md`「安全口径」同批改写（要素不增不删）。
- `tests/test_security_posture_contract.py` 的 `FRAME_ELEMENT_PHRASES[4]` / `AGENTS_ELEMENT_PHRASES[4]`
  追加 `wss` / `SPKI-SHA256 pin`，仍为正向包含。
- **反向证据**：把 `docs/frame.md` 里的 `SPKI-SHA256 pin` 改成占位符 ⇒ `pytest tests/test_security_posture_contract.py -q`
  = `1 failed, 57 passed`（点名 `frame-element-4`）；还原后 = `58 passed`。
- `deploy/README.md` 姿态 3/4 与配置约束、`.env.example` 的 `WS_TLS_*` / `WS_LAN_NO_AUTH` 注释、
  `CHANGELOG.md`（`### Added` + `### Changed（破坏性）`：`tls` 布尔 → 对象）同步。
- `docs/tls-connect-guide.md`（本地资料、不入库）补「落地状态」节。

### 端到端取证（容器内，`172.17.0.3:9299` wss + token；驱动脚本 `.heagent/tmp/e2e_ws_tls.py`）

`16/16 passed`，逐条原始输出见运行日志；关键项：

| 判据 | 结果 |
|---|---|
| `heagent tls init` / `issue --san 172.17.0.3` / `verify` | 三个 `[OK]`，pin `sha256/…`（每轮重签不变） |
| 默认信任库连 wss | `SSLCertVerificationError: unable to get local issuer certificate`（自签不冒充受信） |
| `ca.pem` 作锚 + `check_hostname=True` | 握手成功并收到 `hello version=0.10.0`（SAN 覆盖绑定地址） |
| wss 无 token / 错 token | 各 `HTTP 403` |
| wss + 正确 token | `101` + hello 首帧 |
| 提交 run → 订阅 → cancel | ack `run_id=…`；订阅收到 `{"kind":"cancelled"}` 终态事件 |
| 真实握手叶证书 SPKI vs `heagent tls fingerprint` | 逐字相同（`short=BIRT-B3DJ-G4JY` 那轮） |
| `/api/status` 的 `listeners[].tls` | `enabled=true`、`spki_sha256`/`short_fingerprint` 与 CLI 逐字一致 |
| `heagent doctor`（TLS 三键已配） | `ws_tls_fingerprint` / `ws_tls_expiry` / `ws_tls_san` 三条齐 |
| `WS_LAN_NO_AUTH=true` + `WS_TLS_*` | 进程拒绝启动（exit 1，消息点名两族键） |
| 启动日志 | `ws event=started address=172.17.0.3:9299 listener=external tls=wss auth=token` |

### 未实测 / 待裁决

- **客户端 pin 校验**（`aihome-client` 的 `X509TrustManager`）不在本仓 —— 本仓只证明服务端呈现的 SPKI 与
  发布的 pin 值一致、以及无 token / 错 token 被拒；「pin 改错 ⇒ 握手被拒」属客户端行为，未在本仓实测。
- **宿主真机（Windows）未实测**：本机无 `openssl`，材料只在容器内签发；宿主侧待跑
  `heagent tls --dir .heagent/tls init --force` → `heagent tls issue --san 192.168.2.226` → `heagent tls verify`
  （容器命令：`docker run --rm -v "$PWD:/work" -w /work <含 openssl 的镜像> …`）。
- **`.env` 生产姿态切换未执行（待裁决）**：本机当前仍是 `WS_HOST=192.168.2.226` + `WS_LAN_NO_AUTH=true`
  （第一步明文调试档）。切到 `wss + token` 会让尚未支持 pin 的客户端立即连不上，故留待客户端就绪后由用户决定；
  切换步骤 = `.heagent/tls` 跑 `init --force`（旧材料无 `identity.key`）→ `issue --san 192.168.2.226` →
  `.env` 设 `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE`、`WS_LAN_NO_AUTH=false`、`~/.heagent/setting.md` 配
  `WS_AUTH_TOKEN` → 重启 → `heagent tls fingerprint --format pin` 交给客户端内置。

### 补证（2026-11-21，容器直连**宿主真实 listener** 192.168.2.226:9201）

上一节的三条「未实测」里两条已随姿态切换消解（`.env` 已置 `WS_LAN_NO_AUTH=false` + `WS_TLS_*` 成对 ⇒
`external` / `wss` / `auth=token`；宿主已有 openssl 3.0.16，`init/issue/verify` 可直接在宿主跑）。
本轮从容器以真实客户端打宿主 listener，取证如下（原始输出）：

```
端口矩阵（socket 3s）
  192.168.2.226:9201  OPEN
  192.168.2.226:9301  ConnectionRefused   # Epic 72 已退役，符合预期
  127.0.0.1:9201      ConnectionRefused   # 绑非回环后回环腿消失，符合预期
  192.168.2.226:9101  ConnectionRefused   # HTTP 只绑回环

TLS 握手（ca.pem 作锚 + check_hostname=True）
  TLS: TLSv1.3 TLS_AES_256_GCM_SHA384
  pin   : 247a8b269307d2f682edad8c4f78d7896f99cb47e95a1279667d2de7750fd301
  short : ER5I-WJUT-A7JP
  notAfter: Dec 19 14:48:42 2026 GMT
  SAN   : 127.0.0.1 / ::1 / 10.0.2.2 / 192.168.122.1 / 192.168.2.226 / localhost / heagent.local

无 token 连 wss
  InvalidStatus: server rejected WebSocket connection: HTTP 403   # fail-closed 生效
```

pin 与 `heagent tls fingerprint`（三格式）逐字一致 ⇒ 「客户端 pin 交付」的服务端一侧已可核对；
仍未实测的两项不变：**客户端 `X509TrustManager` 的 pin 校验**（另一仓）与**宿主 `netstat -ano` 行**。
