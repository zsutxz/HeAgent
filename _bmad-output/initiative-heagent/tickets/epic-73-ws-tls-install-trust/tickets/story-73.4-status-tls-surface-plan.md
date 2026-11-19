---
title: 'Story 73.4 `/api/status` 暴露 TLS 身份面'
type: feature
ticket: 4
created: '2026-11-19'
status: done
baseline_revision: '7cc8baba'
route: full
route_source: auto
risk: low
review: quick
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'src/heagent/network/http_protocol.py'
  - 'src/heagent/cli/http_status.py'
  - 'src/heagent/web/status-panel.js'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 排障时「客户端该 pin 哪个指纹」只能上服务器跑命令；`/api/status` 的 listener 条目只有
`tls: bool`，看不到身份。

**Approach:** listener 条目增 `tls` 子对象（`enabled` / `spki_sha256` / `short_fingerprint` /
`not_after` / `san`），未启用时 `enabled=false` 且其余为 `null`；前端部署面展示短指纹。

## Boundaries & Constraints

**Always:**
- 字段值必须与 `heagent tls fingerprint` **逐字一致**（同一实现源：`network/tls_identity.py`）。
- `StatusResponse` 保持 `extra="forbid"`；新增字段只能加在 `tls` 子模型里。
- 未启用 TLS：`enabled=false` + 四个 `null`（不是空串、不是 `[]`）。
- 指纹是公开信息，不因它新增认证面：端点可达性与现有 `/api/status` 完全一致。
- 前端 `_clip` 长度上限沿用；短指纹本身只有 12 字符。

**Never:**
- 不在状态端点里返回私钥、证书全文或 `ca.key` 路径之外的敏感材料。
- 不为这一个字段新增路由。
- 不让前端自己算指纹（必须后端给值，前端只展示）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| TLS_ON | cert/key 配齐 | `tls.enabled=true`，四个字段齐全 | 无 |
| TLS_OFF | 未配 TLS | `tls.enabled=false`，其余 `null` | 无 |
| FINGERPRINT_MATCH | 与 CLI 输出对读 | 逐字相同（`spki_sha256` 与 `short_fingerprint`） | 无 |
| EXTRA_FIELD | 注入未知字段 | 模型校验拒绝（`extra="forbid"`） | 500 由端点闭包固定文案 | 
| FRONTEND_DROP | 删掉面板里的短指纹展示 | 覆盖守卫红 | 点名文件 |

</intent-contract>

## Code Map

- `src/heagent/network/http_protocol.py` — `TlsIdentityInfo` 子模型 + `ListenerInfo.tls` 改类型
  （注意：这是**传输层契约**，改动会影响 `tests/fixtures/contract_baselines/transport_routes.json`
  与既有 `ListenerInfo` 用例）。
- `src/heagent/cli/http_status.py` — 装配期用 `network/tls_identity.py` 计算并填充（惰性缓存，避免每请求读盘）。
- `src/heagent/web/status-panel.js` — 部署面一行「TLS: wss · pin XXXX-XXXX-XXXX · 到期 YYYY-MM-DD」。
- `tests/test_http_status_api.py` / `tests/test_web_server_status_panel.py` — 正负用例 + 字段覆盖。
- `scripts/contract_snapshot.py --write --only transport`（若契约快照含该模型）重生成基线。

## Evidence（开工前取证，交付后回填）

- 已实测：`ListenerInfo` 现为 `(kind, host, port, mode, tls: bool)`（`/api/status` 实测输出形如
  `('ws','172.17.0.3',9201,'lan',False)`）。
- 已实测：`StatusResponse` 使用 `extra="forbid"`（Epic 71 的契约用例钉住）。
