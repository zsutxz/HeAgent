---
type: epic
parent: initiative-heagent
covers: []
sources: ["docs/tls-connect-guide.md"]
companions: ["docs/frame.md"]
after: []
risk: high
---

# WS 内网明文接入（第一步：9201 绑私有 IPv4 + 免 token）

> 状态唯一写目标 = 同目录 `tickets/tickets.toml`；本信封只描述范围、缺口与契约。
> 需求真源 = `docs/tls-connect-guide.md`（第一步的「服务端待改」小节）；客户端改造属 `aihome-client`
> 仓库，**不在本 epic 范围**。

## Description

现状里 WS 入口只有**两种身份**（`docs/frame.md` §4.17.1 / §4.19 要素 3–5）：

- **回环主 listener**（`WS_HOST=127.0.0.1`，默认）= 本地模式：免 token，Host/Origin 防线，
  `/api/cli/ws` 旁路只挂这里；
- **非回环对外 listener**（`WS_EXTERNAL_HOST` 非空，默认端口 `9301`）= 对外模式：强制
  `Authorization: Bearer`、缺 token **拒绝启动**（fail-closed），可配 wss。

`docs/tls-connect-guide.md` 的第一步要的是**第三种身份**：`9201` 绑真内网地址 `192.168.2.226`、
明文、**不设 token**，作为「内网调试入口」。这个组合在今天**起不来**：

- `WS_HOST=192.168.2.226` ⇒ `WsServerConfig.mode == "external"` ⇒ `requires_auth` ⇒ 缺 token 抛
  `WsConfigError`（`config/validation.py::_judge_ws_auth_token` 同口径预检）；
- 若改回 `WS_EXTERNAL_HOST=192.168.2.226` 走对外 listener，就必须配 token 与 TLS，
  与「第一步不设 token」冲突；
- 且对外 listener 身份是**双监听并存**（回环 + 对外），与「`9201` 只绑内网地址、宿主回环不再监听」
  的形态不同。

因此本 epic 做三件互锁的事：**新增 `lan` 监听身份**（私有地址 + 免认证 + 保留 Host/Origin 防线 +
每次启动显性告警）、**退役 9301 双监听与其 `WS_EXTERNAL_*` 配置族**、**把安全口径从「非回环即强制
token」改写成「非回环分 `lan`（显式免认证，仅私有地址）/ `external`（强制 token）」并同步真源与派生副本**。

## 能力缺口（2026-11-19 实测）

| 事实 | 现状 | 缺口 |
|---|---|---|
| 非回环 + 免 token | **不支持**：`WsServerConfig.requires_auth` 只要 `mode != "local"` 即为真 | 无法表达「内网调试入口」这一身份 |
| 绑定到具体网卡地址 | 支持（`WS_HOST` 任意非空串），但绑定后即落对外模式 | 配置能写、起不来 |
| `mode` 取值 | `local` / `external` 两值（`WsServerConfig.mode`、`http_protocol.ListenerMode`） | 状态面与日志无法区分「内网免认证」与「对外带 token」 |
| `9301` 对外 listener | 活着（`.env` 里 `WS_EXTERNAL_HOST=192.168.2.226`、`WS_EXTERNAL_PORT=9301`） | 与第一步「`9301` 不再使用」冲突；同一地址两个入口 |
| `WS_EXTERNAL_*` 配置族 | 5 个键（host / port / readonly / tls cert / tls key）+ CLI 三选项 + `scripts/setup_ws_external.py` | 退役需要全链删除，且 `.env` 残留键今天被 `extra="ignore"` 静默吞掉、**无任何提示** |
| 启动公告 | `ws event=started … listener=local|external tls=…` | 无 `lan` / `auth=none` 事实，排障只能靠猜 |
| `heagent doctor` | 校验对外 listener 四条 fail-loud 组合 | 缺 `lan` 组合的校验（私有地址 / 与 `WS_LOCAL_AUTH_ENABLED` 互斥 / 回环 + 免认证开关） |
| 安全口径 | §4.19 要素 4 = 「非回环强制 Bearer、缺 token 拒绝启动」 | 需要改写为双档（`lan` 显式免认证 / `external` 强制 token），并守住「不倒退」守卫 |

## Outcome

- `WS_HOST=<私有 IPv4>` + `WS_LAN_NO_AUTH=true` 能起来：`netstat` 只看到该地址的 `9201`，
  无 token 的 WS 握手拿到 `101`，客户端可提交 run、订阅事件、收通知流。
- 免认证是**显式开关**而非默认：不带开关仍是 fail-closed；`0.0.0.0` / `::` / 公网地址 /
  主机名 + 该开关 ⇒ **拒绝启动**并给改法。
- `9301` 与 `WS_EXTERNAL_*` 在 `src/`、`scripts/`、`tests/`、`.env.example`、`.env` 中零残留；
  老 `.env` 里的残留键由 `doctor` 一条 INFO 点名「已退役、被忽略」。
- 安全口径只有一份真源（`docs/frame.md` §4.19），派生副本（`AGENTS.md`、`CLAUDE.md`）与
  守卫测试（`tests/test_security_posture_contract.py`）同批改写，**不软化**「本地默认无认证」
  与「对外必须 token」两条。

## Requirements

- 需求真源：`docs/tls-connect-guide.md`「服务端待改」四条——绑 `192.168.2.226`、停用 `9301`、
  放开 `9201` token 校验、`9101` 保持回环。
- 已由用户裁定的前提（同文件「落地前需裁决」）：`9201` 身份 = 内网调试入口、绑真内网地址、
  不绑 `0.0.0.0`、明文全局放行（客户端侧）、**第一步不设 token**；公网入口留第二步另立端点。

## Constraints

- **依赖方向**：私有地址判定住 `network/exposure.py`（`network/` 不得 import `config/` 与运行栈）；
  入口层（`cli/`）只做「配置 → `WsServerConfig`」的装配。
- **fail-loud**：非法组合一律拒绝启动并点名键名与改法，绝不静默降级成「无认证对外」或
  「自动改绑回环」。
- **不新增安全默认缺口**：`lan` 只接受**私有地址字面量**（RFC1918 / 唯一本地 IPv6 / link-local），
  通配与公网地址一律拒绝；免认证必须显式开关；每次启动一条 WARNING。
- **保留 Host/Origin 防线**：`lan` 模式**不**走对外模式的「防线替换」（只有 `external` 跳过同源校验）；
  Android/脚本客户端不带 `Origin`，按既有规则放行，Host 仍需等于绑定地址。
- **硬退役，无别名**：`WS_EXTERNAL_*` 不做兼容层（用户已裁定），迁移靠 `doctor` 提示与 CHANGELOG；
  `Settings` 的 `extra="ignore"` 让老 `.env` 不炸，但必须可见。
- **单文件 ≤1000 行**（`tests/test_architecture_contracts.py`）；不改 `network/ws_server.py` 与
  `network/http_server/` 的隔离约束。
- **口径守卫同批更新**：`tests/test_security_posture_contract.py` 的短语集与谓词分组必须与改写
  同批落地，否则红；`docs/frame.md` 手写 TOC 行随标题改。

## Done when

- `WS_HOST=127.0.0.1`（默认）行为逐字节不变：免 token、旁路照挂、启动公告与现状同形。
- `WS_HOST=<私有 IPv4>` 无 `WS_LAN_NO_AUTH` ⇒ 仍 `WsConfigError`（fail-closed，消息点名两个改法）。
- `WS_HOST=<私有 IPv4>` + `WS_LAN_NO_AUTH=true` ⇒ 起得来；无 token 握手 `101`；
  `/api/status` 的该 listener `mode` 为 `lan`；启动日志有 `listener=lan auth=none` 与一条 WARNING。
- `WS_HOST=0.0.0.0` / `::` / 公网 IPv4 / 主机名 + `WS_LAN_NO_AUTH=true` ⇒ 四条分别拒绝启动。
- `rg "WS_EXTERNAL|ws_external" src/ scripts/ tests/ .env.example` 零命中（历史台账 `_bmad-output/`
  与 CHANGELOG 旧条目除外）；`9301` 在运行期不再出现。
- `pytest`（含 `tests/test_security_posture_contract.py`、`tests/network/`、`tests/test_config_validation.py`、
  `tests/test_cli_doctor.py`）、`ruff check`、`ruff format --check`、`mypy src`、`bandit -r src/ -ll`、
  `mkdocs build --strict` 全绿。
- 宿主真机端到端（`netstat` 绑定 + 无 token 握手 + 提交 run + 订阅事件 + 通知流）留取证记录在
  72.5 的报告里；容器内以容器私有网卡地址做同一套判据。

## Boundaries

- **不做客户端**：`aihome-client` 的 6 处改动、明文放行、免凭据勾选属另一仓库。
- **不做第二步**：不恢复 token、不上 TLS、不做公网端点（`wss://` + Bearer 属 `tls-connect-guide`
  第二步，届时另立 epic/entry）。
- **不动 HTTP 入口**：`9101` 保持回环、无认证、无 TLS；不加对外模式。
- **不做来源白名单**：`lan` 模式明确无认证，不引入「允许哪些客户端 IP」的伪边界。
- **不改 `9301` 之外的历史台账**：归档的 v6 `epics.md` 与既有 retrospective 正文不回洗。

## 已定的裁决与残差

- **已定**：`lan` 用显式开关 `WS_LAN_NO_AUTH`（默认关）；只接受私有地址字面量；每次启动一条
  WARNING；免认证 listener 的 `mode` 名为 `lan`（`ListenerMode` 加第三值）。
- **已定**：`WS_CLI_BYPASS_ENABLED` 旁路仍**只挂本地模式**（保持 D9「终端内容不外溢」不变量）
  ⇒ `WS_HOST` 非回环时旁路自动跳过并 WARNING。代价：第一步之后终端旁路在局域网不可见，
  这是刻意的（旁路内容含交互终端里尚未提交的输入）。
- **已定**：`/api/notifications/ws` 在 `lan` listener 上**照挂**（`CRON_PUSH_ENABLED=true` 时），
  因为客户端「三处对账」要求 `PUSH_CONNECTED`；代价（cron 的 LLM 输出对同网段可见）写进 WARNING
  与文档。
- **残差**：DHCP 换租会让已保存端点失效（网络侧静态绑定，代码不处理）；同一内网任何设备可驱使
  代理（无认证的必然代价，靠网络侧兜底）；`WS_AUTH_TOKEN` 在第一步期间留在 `setting.md` 但主
  listener 不再使用（第二步恢复）。

## References

- 需求与实测：`docs/tls-connect-guide.md`（服务端待改 / 验证顺序 / 常见排障 / 红线）
- 监听配置与模式：`src/heagent/network/ws_host.py::WsServerConfig`（`mode` / `requires_auth` /
  `_validate_auth_and_tls`）、`src/heagent/network/ws_auth.py`（`make_authorizer`）
- 暴露判定唯一判据点：`src/heagent/network/exposure.py::is_loopback_host`
- 装配：`src/heagent/cli/http_config.py::build_ws_servers` / `build_external_ws_server_config`、
  `src/heagent/cli/http.py`（`--ws-external-*` 三选项）
- 启动期预检：`src/heagent/config/validation.py::_judge_ws_auth_token` / `_judge_ws_external_binding`
- 诊断：`src/heagent/cli/doctor.py`（WS 面 findings、端口占用候选）
- 状态面：`src/heagent/network/http_protocol.py::ListenerMode` / `ListenerInfo`
- 口径真源：`docs/frame.md` §4.17.1 / §4.19；派生：`AGENTS.md`「⚠️ 安全声明」、`CLAUDE.md`「安全口径」；
  守卫：`tests/test_security_posture_contract.py`
- 手工探针：`scripts/ws_manual_probe.py`（已支持 `ws://` 明文与可选 `--token`）
