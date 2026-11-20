---
epic: epic-73-ws-tls-install-trust
date: 2026-11-19
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 73 Retrospective

> 路径约定：`tickets/story-73.*` 相对 `_bmad-output/Goal-3/tickets/epic-73-ws-tls-install-trust/`；
> 其余路径相对仓库根。门禁实测为交付时现场复跑（容器内 `.heagent/tmp/py311-venv-linux/bin/python`，
> `PATH` 前置 `node v20.18.1`）。

## Epic summary

**Epic**：epic-73-ws-tls-install-trust（risk 高；6 story，全部新建，`after` 链 1→2→{3,4}→5→6）

**票态**：6/6 `done`，无 `dropped`。交付 = **六个提交**：`eeef5d77`（73.1）/ `29461084`（73.2）/
`ff68e476`（73.3）/ `95b16c5b`（73.4，与 73.3 并行开发）/ `4a82b276`（73.5）/ `2f1e8ff4`（73.6）。

**需求真源**：`docs/tls-connect-guide.md`「第二步」节（gitignored）+ ADR-004
（`decisions/adr-ws-tls-install-time-trust.md`）。客户端改造属 `aihome-client` 仓库，不在本 epic。

| Entry | 交付 | 关键判据 |
|---|---|---|
| 73.1 身份密钥与叶证书分离 | `network/tls_identity.py`（纯 stdlib ASN.1 遍历：SPKI 原始 TLV / 摘要 / 短指纹 / 有效期 / SAN / cert↔key 配对）+ `scripts/gen_ws_cert.py` 复用 `identity.key`（新增 `--rotate-key`）+ `tests/fixtures/tls/` | SPKI-SHA256 与 `openssl pkey -pubin -outform der \| sha256` 逐字节一致（夹具 `d5af625c…`，现有 `cert.pem` `b14417f5…`）；重签两次 pin 不变、`--rotate-key` 后变而 CA 不变 |
| 73.2 `heagent tls` 命令族 | `cli/tls_cmd.py`：`init` / `issue` / `rotate-key` / `fingerprint`（text/json/pin）/ `verify`；注册进 `console.py` | `tests/test_cli_tls.py` 22 例（真实 openssl）：幂等 init、`--force` 留底、复用重签 pin 不变、rotate 需 `--yes`、三格式同哈希、verify 逐条 FAIL |
| 73.3 启动自检与 doctor 三项 | `cli/http_config.py::_check_tls_identity`（到期 < 7 天 / SAN 漂移各一条 WARNING，时钟可注入）+ `WsServerConfig` 构造期 cert↔key 配对 fail-loud + `doctor.ws_tls_{fingerprint,expiry,san}`（材料坏掉 `ws_tls_unreadable`） | `tests/test_cli_tls_selfcheck.py` 26 例（`caplog` 计数恰一条；阈值常量单源）；`docs/errors.md` 两条启动拒绝文案 |
| 73.4 `/api/status` TLS 身份面 | `http_protocol.TlsIdentityInfo`（`extra=forbid` + 「启用 ⇔ 四项齐全」模型校验）、`ListenerInfo.tls` 布尔 → 对象、`http_status` 按「路径 + mtime」惰性缓存、`status-panel.js` 部署面加身份行 | `tests/test_http_status_api.py` / `test_web_server_status_panel.py`（含 node 探针）；与 `heagent tls fingerprint` 逐字一致；传输契约基线未变（无新路由） |
| 73.5 wss + token 与明文回收 | `wss` + `WS_LAN_NO_AUTH` 三处互斥（模型 / 装配层 / 启动前预检）；启动日志 `tls=wss auth=token`；`docs/errors.md` 新增「四、客户端 TLS 稳定错误码」 | `tests/test_ws_lan_mode.py` + `tests/network/test_ws_e2e.py`（真实 wss：无/错 token 403、对 token 101、`started` 日志含两字段） |
| 73.6 端到端验收与口径同步 | frame §4.19 要素 4、AGENTS/CLAUDE 派生、守卫短语集（+`wss` / `SPKI-SHA256 pin`）；`deploy/README.md` / `.env.example` / `CHANGELOG.md` | 反向证据：删短语 ⇒ 守卫红（`1 failed, 57 passed`，点名 `frame-element-4`），还原后 `58 passed`；容器内端到端 16/16 |

## 端到端证据（容器内，私网 `172.17.0.3:9299` wss + token）

```text
tls init / issue --san 172.17.0.3 / verify        PASS  三个 [OK]，pin sha256/…
默认信任库连 wss                                  PASS  SSLCertVerificationError: unable to get local issuer certificate
ca.pem 作锚 + check_hostname=True                 PASS  hello version=0.10.0
wss 无 token / 错 token                            PASS  HTTP 403 / HTTP 403
wss + 正确 token                                   PASS  101 + hello
提交 run → 订阅 → cancel                            PASS  ack run_id=…；收到 {"kind":"cancelled"}
真实握手叶证书 SPKI vs `tls fingerprint`            PASS  逐字相同
/api/status listeners[].tls                       PASS  enabled=true，摘要与 CLI 一致
heagent doctor（TLS 三键已配）                      PASS  ws_tls_fingerprint / ws_tls_expiry / ws_tls_san
WS_LAN_NO_AUTH=true + WS_TLS_*                    PASS  拒绝启动（exit 1，点名两族键）
启动日志                                           PASS  ws event=started … listener=external tls=wss auth=token
```

## 门禁（交付时实测）

- 全量 `pytest`：**5610 passed / 0 failed / 17 skipped / 1 xfailed**（`PATH` 前置 node v20.18.1，前端探针真跑）
- `ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll`（0 medium+）/ `contract_snapshot --check`（四份基线一致）/ `mkdocs build --strict`（0 warning）：全绿

## 经验（可复用）

1. **pin 的对象必须是密钥不是证书**：把「重签复用 `identity.key`」当成地基，`issue` 里显式比对
   「重签前后 SPKI 是否相同」并在不同时报错——这条自检把「实现漂移导致 pin 每 30 天失效」变成红灯。
2. **纯 stdlib ASN.1 可行但要按真实长度头写**：把 DER 长度头写死 2 字节会得 292 字节（错）而不是 294；
   判据必须是「与 openssl 输出逐字节相同」，不是「看着像」。
3. **网络层的错误类型留在本层**：`TlsIdentityError` 定义在 `network/tls_identity.py`（`ValueError` 子类），
   不引入 `network/ → pub.exceptions` 的新依赖，同时保持 fail-loud 与可捕获。
4. **并行 lane 的文件域必须写进任务书**：73.3 / 73.4 各自 lane 被明确禁止碰对方的
   `http_config.py` / `ws_server` / `http_protocol.py`，两条 lane 同时在树里也没有互相覆盖；
   两个子 Agent 都撞了 60 迭代上限、没有回报，但工作树是完整可验收的半成品（先 `git status` 再验收）。
5. **阈值常量单源**：`TLS_EXPIRY_WARNING_DAYS` 同时被启动自检与 doctor 使用，测试直接断言该常量，
   避免「两处各写 7」。

## Open questions（已升台账）

- **A76**：宿主真机（Windows 无 openssl）签发与 `netstat` 对账未跑；客户端 `aihome-client` 的
  `X509TrustManager` pin 校验属另一仓；`.env` 生产姿态切换（`WS_TLS_*` + 关 `WS_LAN_NO_AUTH`）会让
  尚未支持 pin 的客户端立刻断连 ⇒ **待用户裁决**。切换步骤已写进
  `tickets/story-73.6-e2e-and-posture-sync-plan.md` 的 Evidence。
