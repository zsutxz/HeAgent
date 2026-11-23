---
type: epic
parent: initiative-heagent
covers: []
sources: ["docs/tls-connect-guide.md", "docs/decisions/adr-0004-ws-tls-install-time-trust.md"]
companions: ["docs/frame.md"]
after: []
risk: high
---

# WS TLS 安装期信任（第二步：wss + token，客户端只认 pin）

> 状态唯一写目标 = 同目录 `tickets/tickets.toml`；本信封只描述范围、缺口与契约。
> 决策真源 = `docs/decisions/adr-0004-ws-tls-install-time-trust.md`（ADR-004）。
> 需求真源 = `docs/tls-connect-guide.md`「第二步」节（该页 gitignored，故决策正文以 ADR 为准）。

## Description

第一步（Epic 72）把 `9201` 做成**内网明文、免 token** 的调试入口。第二步要把它变成
**`wss://` + Bearer token**，但客户端侧有三处硬约束（2026-11-19 实测于 `aihome-client` 证据链）：

1. 客户端按**整张叶子证书**匹配「导入记录」，叶子默认 30 天到期 ⇒ 每台设备每 30 天重导一次；
2. 「信任并锁定」的唯一入口是导入记录，而现版本界面上建不起来 ⇒ 连「导一次长期用」都不成立；
3. 内网地址会漂移（DHCP / 换网段 / 换网卡）⇒ 主机名校验必然误伤。

用户裁定（2026-11-19）：**客户端不导证书，安装时信任服务器即可**。据此本 epic 把信任锚改成
**服务端身份公钥的 SPKI-SHA256**（ADR-004），服务端负责让这个锚长期稳定：

- 身份密钥与叶证书**分离**，重签复用密钥 ⇒ pin 不随 30 天轮换失效；
- `heagent tls` 命令族提供签发 / 轮换 / 指纹导出 / 一致性校验的**唯一入口**；
- 启动与 `doctor` 自检把「到期」「SAN 不含当前绑定」「cert 与 key 不配对」三条静默失联风险显性化；
- `/api/status` 暴露短指纹供排障核对；
- 最后落地 wss + token、回收明文放行，并把安全口径与客户端契约写进真源。

## 能力缺口（2026-11-19 实测）

| 事实 | 现状 | 缺口 |
|---|---|---|
| 重签叶证书是否换密钥 | `scripts/gen_ws_cert.py::issue_leaf` 每次 `genrsa -out key.pem 2048` ⇒ **换新密钥** | pin 每 30 天失效，「安装期信任」不成立 |
| SPKI 指纹计算 | 无任何实现；核心依赖只有 6 项、不含 `cryptography` | 需纯 stdlib 的最小 DER/ASN.1 取 SPKI（已实测可行：现有 `cert.pem` 取出 294 字节，SHA-256 = `b14417f5…`，与 `openssl` 一致） |
| 签发与轮换入口 | 一次性脚本 `scripts/gen_ws_cert.py`（容器内跑 openssl），无命令族、无 `verify` | 签发 / 轮换 / 指纹导出无统一入口，也无一致性校验 |
| 到期与 SAN 漂移可见性 | `doctor` 只有 `doctor.ws_tls_half_configured`（cert/key 只配一个） | 到期余量、SAN 覆盖当前绑定地址、cert 与 key 配对全部不可见 |
| TLS 身份是否对外可见 | `/api/status` 的 listeners 只有 `tls: bool` | 排障时无法确认「客户端该 pin 哪个指纹」 |
| token 与 TLS 组合 | 第一步 `WS_LAN_NO_AUTH=true` 免 token 明文；`wss` + `lan` 未定义 | 加密与免认证可以同时成立（自相矛盾），需 fail-loud |
| 客户端信任契约 | 只有「导入叶子 / 系统链 / 锁定」三套旧路径 | pin 校验三条、双 pin 轮换、稳定错误码均无成文契约 |

## Outcome

- 服务端身份密钥长期固定：**叶证书重签（30 天或换 SAN）后 SPKI 不变**，客户端 pin 零动作。
- `heagent tls init / issue / rotate-key / fingerprint / verify` 是签发与轮换的**唯一入口**；
  `rotate-key` 是唯一会改变 pin 的动作，且必须显式执行并打印新旧两个指纹。
- TLS 启用时，到期 < 7 天、SAN 不含当前绑定地址、cert 与 key 不配对三种情形在**启动期**可见
  （前两条 WARNING、第三条拒绝启动），`doctor` 同口径可查。
- `/api/status` 的 listener 条目给出 `spki_sha256` / `short_fingerprint` / `not_after` / `san`，
  与 `heagent tls fingerprint` 逐字一致。
- `wss` + Bearer token 可用；`wss` + `WS_LAN_NO_AUTH=true` 拒绝启动；第一步的明文放行按文档清单回收。
- 安全口径真源（`docs/frame.md` §4.19 要素 4/5）与派生副本（`AGENTS.md` / `CLAUDE.md`）同批改写，
  守卫测试短语集同步，**不软化**「加密 + token 才算第二步」与「`lan` 是显式调试档」。

## Requirements

- 信任锚 = 服务端身份公钥的 SPKI-SHA256，客户端只校「pin + 有效期」，**不校主机名**（ADR-004）。
- 安装期信任三种交付形态：A 构建期内置 pin（默认）、B 构建期内置 CA、C 安装向导 TOFU 核对；
  服务端为三者提供同一套指纹事实（`fingerprint` 命令 + `/api/status` + 启动公告）。
- 短指纹格式统一：SPKI-SHA256 的 base32 前 10 字节，按 `XXXX-XXXX-XXXX` 分组。
- 客户端改造属 `aihome-client` 仓库，**不在本 epic 范围**；本 epic 只交付契约与稳定错误码
  （`pin_mismatch` / `cert_expired` / `cert_unreadable`）。

## Constraints

- **零新增运行时依赖**：核心依赖保持 6 项，SPKI 解析用纯 stdlib（`hashlib` + 手写 ASN.1 遍历）；
  签发仍用 `openssl` 子进程（仅 CLI 路径，不在请求路径上）。
- **依赖方向**：`network/tls_identity.py` 只依赖 stdlib（`network/` 不得 import `config/` 与运行栈）；
  材料路径与 `Settings` 键由入口层（`cli/`）传入。
- **fail-loud**：cert 与 key 不配对、`wss` + `lan` 同时成立一律拒绝启动并点名键名与改法；
  到期与 SAN 漂移不得静默。
- **私钥纪律**：`ca.key` / `identity.key` 永不外发、不入库、不进日志；`chmod 0600` 沿用 best-effort
  （9p/drvfs 上 EPERM 属预期，只提示不中断）。
- **单文件 ≤1000 行**；`network/ws_server.py` 不得 import `network/http_server.py` 等既有边界不变。
- **口径守卫同批更新**：`tests/test_security_posture_contract.py` 的短语集与谓词分组、`docs/frame.md`
  手写 TOC 行，均须与改写同批落地。

## Done when

- 复用身份密钥重签两次 ⇒ `heagent tls verify` 绿、`spki_sha256` 逐字相同、`not_after` 变化。
- `heagent tls rotate-key` ⇒ 打印 old/new 指纹与双 pin 过渡提示；旧 pin 在此后握手被拒（反向用例）。
- 到期 3 天夹具启动 ⇒ 恰一条 WARNING；SAN 缺当前绑定 ⇒ WARNING；cert/key 不配对 ⇒ 拒绝启动。
- `wss` 真实握手：`ca.pem` 作信任锚成功、无 token `403`、正确 token `101`；
  `WS_LAN_NO_AUTH=true` + TLS ⇒ 拒绝启动。
- `/api/status` 的 `tls.short_fingerprint` 与 `heagent tls fingerprint` 逐字相同；
  未启用 TLS 时四字段为 `null`。
- `pytest`（全量）、`ruff check`、`ruff format --check`、`mypy src`、`bandit -r src/ -ll`、
  `mkdocs build --strict` 全绿；`tests/test_security_posture_contract.py` 反向删短语会红。
- 宿主真机不可达项明确标 `未实测` 并列出用户可执行的命令清单。

## Boundaries

- **不做客户端**：`aihome-client` 的 pin 内置、握手校验、错误码映射、UI 文案属另一仓库。
- **不改第一步的验收面**：`9201` 的绑定地址、`WS_LAN_NO_AUTH` 的语义与「每次启动一条 WARNING」
  不变；本 epic 只是把生产档改成 wss + token，`lan` 保留为显式调试档。
- **不引公共 CA / tailnet**：附录 A 的组网公共证书方案仍是备选，不在本 epic 实施。
- **不做多端点多租户**：一台服务端一套身份密钥；多服务端各自 pin（形态 B 才需要 CA 统管）。
- **不做证书吊销 / OCSP / CT 账本**：pin 模型下吊销 = 轮换身份密钥，走 `rotate-key`。

## 已定的裁决与残差

- **已定**（ADR-004）：信任锚 = SPKI pin；叶证书重签复用身份密钥；客户端不校主机名；双 pin 过渡；
  `rotate-key` 是唯一改变 pin 的动作且必须显式执行。
- **已定**：短指纹 = SPKI-SHA256 的 base32 前 10 字节，`XXXX-XXXX-XXXX` 分组（人眼核对用，
  不是安全边界的替代——真正校验仍用完整 SHA-256）。
- **残差（预期）**：pin 泄露无第二道约束（无域名 / 无链 / 无 CT）；身份密钥轮换需要人工介入与客户端
  重发安装包（双 pin 窗口可缩短这段）；SAN 随内网地址漂移仍需重签（只是重签不再影响 pin）。
- **残余风险**：`heagent tls` 依赖 `openssl` 二进制（签发路径）；宿主 Windows 无 openssl 时须在容器内
  执行（既有先例，`scripts/gen_ws_cert.py` 已如此）。

## References

- 决策：`docs/decisions/adr-0004-ws-tls-install-time-trust.md`
- 需求与实测：`docs/tls-connect-guide.md`「第二步」节 / 附录 A / 常见排障 / 红线
- 现有签发脚本：`scripts/gen_ws_cert.py`（`issue_leaf` 换密钥的那一行是 73.1 的改动点）
- 材料布局：`.heagent/tls/`（`ca.pem` / `ca.key` / `cert.pem` / `key.pem` / `cert-chain.pem` /
  `openssl-leaf.cnf` / `ca.srl`，已 gitignore）
- 监听与 TLS 开关：`src/heagent/network/ws_host.py::WsServerConfig`（`tls_enabled` / `requires_auth` /
  `_validate_auth_and_tls`）、`src/heagent/cli/http_config.py`
- 自检：`src/heagent/cli/doctor.py`（现只有 `doctor.ws_tls_half_configured`）
- 状态面：`src/heagent/network/http_protocol.py::ListenerInfo` / `cli/http_status.py`
- 口径真源：`docs/frame.md` §4.17.1 / §4.19；派生：`AGENTS.md`、`CLAUDE.md`；
  守卫：`tests/test_security_posture_contract.py`
- 手册探针：`scripts/ws_manual_probe.py`（已支持 `wss://` 与 `--token`）
