---
title: 'Story 73.5 wss listener + 恢复 Bearer token + 明文回收'
type: feature
ticket: 5
created: '2026-11-19'
status: ready-for-dev
baseline_revision: '7cc8baba'
route: full
route_source: auto
risk: high
review: thorough
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'src/heagent/network/ws_host.py'
  - 'src/heagent/cli/http_config.py'
  - 'src/heagent/config/validation.py'
  - 'docs/errors.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 第一步的 `lan` 档是「明文 + 免 token」，与第二步的「加密 + token」在配置面上可以同时成立
（`WS_TLS_*` 配齐 + `WS_LAN_NO_AUTH=true`）⇒ 系统会给出一个自相矛盾的姿态：加密了却不认证。
同时 `wss` 的客户端契约（pin 校验、错误码）没有成文出处。

**Approach:** 让 `wss` 成为「非 `lan` 档必带 token」的常态：`wss` + `WS_LAN_NO_AUTH` 拒绝启动；
`external` 档恢复 token 校验；把客户端契约三条与三个稳定错误码写进 `docs/errors.md` 与 guide。

## Boundaries & Constraints

**Always:**
- `wss` + `WS_LAN_NO_AUTH=true` ⇒ **拒绝启动**，消息点名两键与两个改法（关开关 / 停 TLS）。
- `external` 档 `requires_auth` 恒为真；缺 token 仍 fail-closed（沿用 Epic 56/72 语义）。
- 启动公告与日志必须写清 `tls=wss auth=token`（不再只有 `tls=ws`）。
- `/api/cli/ws` 旁路仍只挂回环（Epic 72 的 D9 不变量不因 TLS 改变）。
- 客户端契约三条（pin / 有效期 / 不校主机名）与错误码 `pin_mismatch` / `cert_expired` /
  `cert_unreadable` 写进 `docs/errors.md`（稳定码表）与 guide 第二步节。
- 中间态（明文 + token）只在隔离内网允许，文档明确禁止跨不可信网络使用。

**Never:**
- 不把 `lan` 档删除（它是显式调试入口，仍要能在隔离内网开）。
- 不引入「可选跳过 TLS 校验」的服务端开关（服务端不参与客户端信任决策）。
- 不改 `network/ws_server.py` 与 `network/http_server/` 的隔离约束。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| WSS_TOKEN_OK | `WS_HOST=<私有 IPv4>` + TLS 配齐 + token | 握手 `101`，`Authorization: Bearer` 通过 | 无 |
| WSS_NO_TOKEN | 同上，不带头 | `403` | 稳定错误码 |
| WSS_BAD_TOKEN | 同上，错 token | `403` | 同上 |
| WSS_LAN_CONFLICT | TLS 配齐 + `WS_LAN_NO_AUTH=true` | 拒绝启动 | 点名两键，退出码 1 |
| PLAINTEXT_TOKEN | 明文 + token（中间态） | 隔离内网可用 | 文档标注风险 |
| LOOPBACK_DEFAULT | `WS_HOST=127.0.0.1` + TLS 配齐 | `local` 档仍免 token（既有语义），日志 `tls=wss` | 无 |
| CLI_BYPASS | 非回环 wss | `/api/cli/ws` 不注册，WARNING `reason=non_loopback_listener` | 无 |

</intent-contract>

## 客户端契约（本仓只定契约，实现在 `aihome-client`）

### 关键陷阱：`CertificatePinner` 单独用不够

自签证书**过不了系统 trust store**，而 OkHttp 的 `CertificatePinner` 只在链校验**通过之后**才做 pin ⇒
只加 pin 会先死在「证书不受信」。正确形态是**自定义 `X509TrustManager`**：

```
// 形态 A：只认 pin（不校链、不校主机名）
class PinOnlyTrustManager(pins: List<ByteArray>) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String): Array<X509Certificate> {
        val leaf = chain.firstOrNull() ?: throw CertificateException("cert_unreadable")
        val digest = MessageDigest.getInstance("SHA-256").digest(leaf.publicKey.encoded)   // publicKey.encoded == SPKI DER
        if (pins.none { MessageDigest.isEqual(it, digest) }) throw PinMismatch(digest)     // 常量时间比较
        if (leaf.notAfter.before(Date())) throw CertificateExpired(leaf.notAfter)
        return arrayOf(leaf)          // Android：返回空数组会 NPE，必须回传叶证书
    }
    override fun checkClientTrusted(...) = throw UnsupportedOperationException()
    override fun getAcceptedIssuers() = emptyArray<X509Certificate>()
}
okHttpClient = okHttpClient.newBuilder()
    .sslSocketFactory(SSLContext.getInstance("TLS").apply {
        init(null, arrayOf(PinOnlyTrustManager(pins)), null)
    }.socketFactory, PinOnlyTrustManager(pins))
    .hostnameVerifier { _, _ -> true }        // 刻意豁免：身份由 pin 承担（ADR-004）
    .build()
```

- `Certificate.publicKey.encoded` 在 JCA 里**就是** SPKI DER，与 `heagent tls fingerprint` 同源，
  客户端**不需要**自己解析 ASN.1。
- WebSocket 走同一个 `OkHttpClient`，TLS 配置自动继承。
- 形态 B（内置 CA）改为：`CertificateFactory` 载入 `res/raw/heagent_ca.pem` → `KeyStore` →
  `TrustManagerFactory` 初始化；**仍保留 `hostnameVerifier { _, _ -> true }`**（内网地址会变）。
- 形态 C（TOFU）只在首次连接用「先接受 + 记录 pin + 展示短码」，核对后写进持久化 pin 集合。

### 错误码映射（客户端本地判定，服务端不产生）

| 场景 | 错误码 | 判据 | UI 要点 |
|---|---|---|---|
| pin 不匹配 | `pin_mismatch` | `digest` 不在 pin 集合 | 同时显示「期望 / 实际」两个短指纹 |
| 证书过期 | `cert_expired` | `notAfter < now` | 显示到期日 + 提示服务端执行 `heagent tls issue` |
| 证书不可读 | `cert_unreadable` | 链为空 / 解析失败 / 握手无证书 | 提示检查端点与端口是否指向 WS listener |
| 主机名不匹配（不应出现） | `pin_mismatch` | 若出现说明仍在旧 trust 路径 | 诊断信息注明 `legacy_trust_path` |

- 服务端只保证「wss 起得来、token 生效」；信任判定全在客户端，服务端不参与、也不提供「跳过校验」开关。
- 服务端日志里可出现 `pin_mismatch` 字样仅当客户端把它作为文本上报；服务端**不**据此放行任何连接。

### pin 交付格式与轮换

- 服务端输出三种形态（`heagent tls fingerprint --format text|json|pin`）：
  `text` = 四段人读；`json` = 供脚本/构建流水线；`pin` = `sha256/<base64(SPKI-SHA256)>`（OkHttp 风格）。
- 客户端 pin 集合最多 **2** 个（old + new），超过即配置错误（构建期断言）。
- 轮换时序：服务端 `rotate-key`（打印 old/new）→ 客户端发布内置 `old+new` → 全部设备升级 →
  下一次发布移除 `old`。服务端**不追踪**客户端 pin（无状态，也不引入设备注册）。

## Code Map

- `src/heagent/network/ws_host.py` — `_validate_auth_and_tls` 增 `tls + lan_no_auth` 互斥；启动公告补 `auth=` 字段。
- `src/heagent/cli/http_config.py` — 装配点同步公告与 `tls=` 事实。
- `src/heagent/config/validation.py` — `_judge_ws_auth_token` / `_judge_ws_tls_pair` 增互斥预检（启动前可见）。
- `docs/errors.md` — 三个客户端稳定错误码。
- `docs/tls-connect-guide.md` — 第二步「与第一步的衔接」补错误码与中间态禁令（该页本地资料）。
- `tests/test_ws_lan_mode.py` / `tests/network/test_ws_server.py` — 新增互斥与 wss 用例。

## Evidence（开工前取证，交付后回填）

- 已实测（Epic 72 期内）：`WsServerConfig.mode` 三值；`_validate_auth_and_tls` 已有三条准入；
  启动公告 `ws event=exposed … listener=lan auth=none tls=ws`。
- 已实测：`scripts/ws_manual_probe.py` 支持 `wss://` 与 `--token`，可直接做真实握手取证。
