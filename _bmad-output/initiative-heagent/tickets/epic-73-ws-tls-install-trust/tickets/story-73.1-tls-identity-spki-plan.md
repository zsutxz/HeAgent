---
title: 'Story 73.1 身份密钥与叶证书分离（SPKI 稳定）'
type: feature
ticket: 1
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
  - 'src/heagent/network/tls_identity.py'
  - 'scripts/gen_ws_cert.py'
  - 'tests/test_tls_identity.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 「安装期信任」要求客户端 pin 一个**长期不变**的值，但现状
`scripts/gen_ws_cert.py::issue_leaf` 每次重签都 `genrsa -out key.pem 2048` 生成新密钥 ⇒ 证书里的
公钥每次都变 ⇒ 任何 pin 都会在 30 天后失效。同时仓内没有任何 SPKI 指纹实现，而核心依赖只有 6 项、
不含 `cryptography`。

**Approach:** 引入长期 `identity.key`（叶证书签发时复用），并新增纯 stdlib 的
`network/tls_identity.py`：最小 ASN.1 遍历取 `SubjectPublicKeyInfo` 的**原始 TLV**（含 tag 与长度头），
据此算 SPKI-SHA256、短指纹、cert↔key 配对判定与 SAN 覆盖判定。

## Boundaries & Constraints

**Always:**
- 纯 stdlib（`hashlib` / `base64` / `binascii`），**不新增依赖**；核心 `dependencies` 保持 6 项。
- SPKI 取的是**整个元素**（tag + 长度字节 + 内容），与 `openssl pkey -pubin -outform der` 逐字节一致；
  长度头宽度必须按实际长度字节推导（长格式 `0x81/0x82` 时头是 2/3 字节），不得写死 2 字节。
- `identity.key` 首次 `init` 生成后不再自动变；变更只经 `heagent tls rotate-key`（73.2）。
- 材料路径由调用方传入（`network/` 不得 import `config/`）；函数签名接受 `Path` 或 `bytes`。
- 失败一律显性：PEM 解不出、DER 结构不符、非证书、key 不配对 → 抛 `TlsIdentityError`（`pub/exceptions.py`）。

**Never:**
- 不在请求路径上跑 `openssl`（签发/校验只在 CLI 与启动自检，且 `tls_identity` 本身不调子进程）。
- 不把私钥内容写进日志或异常消息（只报路径与「无法读取/不配对」）。
- 不为了让测试通过而放宽 ASN.1 校验（宁可显性抛错）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| SPKI_MATCH_OPENSSL | 现有 `cert.pem`（RSA 2048） | SHA-256 = 294 字节 TLV 的摘要，与 `openssl` 一致（实测 `b14417f5…`） | 无 |
| REUSE_KEY | 复用 `identity.key` 重签两次 | 两次 `spki_sha256` 相同；`not_after` 与序列号变化 | 无 |
| WRONG_KEY | `cert.pem` + 别的 `key.pem` | `cert_key_matches` = False | 返回布尔，不抛 |
| BAD_PEM | 非 PEM 文本 / 空文件 | 抛 `TlsIdentityError`，消息含路径 | 显性抛错 |
| NON_CERT_DER | 合法 PEM 但不是证书（如 CSR） | 抛 `TlsIdentityError`（结构不符） | 显性抛错 |
| SAN_HIT_IP | SAN 含 `192.168.2.226` | `san_covers` = True | 无 |
| SAN_MISS | SAN 无该地址 | False | 无 |
| SAN_HOSTNAME | 传 `example.lan` | 只匹配 DNS 项，不匹配 IP 项 | 无 |
| SHORT_FP | 任意证书 | 12 字符 `XXXX-XXXX-XXXX`（base32 前 10 字节） | 无 |

</intent-contract>

## Code Map

- `src/heagent/network/tls_identity.py`（新增，约 120 行）— `TlsIdentityError`（或复用 `pub/exceptions.py` 新增类）、`load_cert_der`、`spki_der(cert)`、`spki_sha256(cert)`、`short_fingerprint(cert)`、`cert_not_after(cert)`、`san_entries(cert)`、`san_covers(cert, host)`、`cert_key_matches(cert, key)`。
- `src/heagent/pub/exceptions.py` — 若新增异常类，须同步 `scripts/contract_snapshot.py --write --only exceptions` 重生成 `tests/fixtures/contract_baselines/exception_types.json`。
- `scripts/gen_ws_cert.py` — `issue_leaf` 改为：`identity.key` 存在则复用（`req -new -key identity.key`），否则首次生成；`--rotate-key` 才重生成。
- `tests/test_tls_identity.py`（新增）— 夹具 PEM 放 `tests/fixtures/tls/`（cert/key/expired/wrong-key），逐条覆盖上表。
- `tests/test_architecture_contracts.py` — `network/` 只依赖 stdlib 的边界已有断言；新模块须通过（不得 import `config/`）。

## Evidence（开工前取证，交付后回填）

- 已实测（2026-11-19，容器内）：现有 `.heagent/tls/cert.pem` 的 SPKI = 294 字节，
  SHA-256 = `b14417f507b9f2c682b021ec01b9e57886464172e9ad4ef2364e8bc8b58a14b0`，
  与 `openssl x509 -pubkey -noout | openssl pkey -pubin -outform der | openssl dgst -sha256` 逐字一致。
- 已实测：第一次尝试把长度头写死 2 字节得到 292 字节 / `2178c362…`（错）⇒ 用例必须覆盖长格式长度头。
