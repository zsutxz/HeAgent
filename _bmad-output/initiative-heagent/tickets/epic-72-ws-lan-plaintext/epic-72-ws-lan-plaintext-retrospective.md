---
epic: epic-72-ws-lan-plaintext
date: 2026-11-19
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 72 Retrospective

> 路径约定：`tickets/story-72.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-72-ws-lan-plaintext/`；
> 其余路径相对仓库根。门禁实测为 2026-11-19 补做本 retro 时现场复跑
> （容器内 `.heagent/tmp/py311-venv-linux/bin/python`，`PATH` 前置 `node v20.18.1`）。

## Epic summary

**Epic**：epic-72-ws-lan-plaintext（risk 高；5 story，全部新建，`after` 串行链 1→2→3→4→5）

**票态**：5/5 `done`，无 `dropped`。交付 = **单提交** `5e1f3c9e`（42 文件，+1431 / −1080）。

**需求真源**：`docs/tls-connect-guide.md` 第一步的「服务端待改」小节（客户端改造属 `aihome-client` 仓库，不在本 epic）。

| Entry | 交付 | 关键判据 |
|---|---|---|
| 72.1 `lan` 监听身份 | `network/exposure.py::is_private_address`（`ipaddress` 判定，只认 IP 字面量，不解析 DNS）+ `WsServerConfig.lan_no_auth` + `mode` 三值（`local` / `lan` / `external`）+ 三条准入 fail-loud | `tests/test_ws_lan_mode.py`（282 行）；真实 TCP：私网地址无 token `ping` → `{"type":"ack",...}`；同 listener `Host: evil.example` 被 `origin_rejected / host not allowed` 拒 |
| 72.2 退役对外 listener 与 `WS_EXTERNAL_*` | 硬删除五键 + `--ws-external-*` 三选项 + `9301` + `scripts/setup_ws_external.py`（231 行）与其测试（156 行）；`doctor.retired_key` 提示残留键 | `rg "9301" src/` 空；`rg "WS_EXTERNAL" src/ scripts/` 只命中退役键表与迁移文案 |
| 72.3 自检与排障面 | `cli/doctor.py` 三条 `ws_lan_*` findings + 启动公告三档（`listener=local\|lan\|external`）+ 拒绝启动文案点名两个改法 + `ws_manual_probe.py` 用法示例 + `faq.md` / `errors.md` 改写 | `pytest tests/test_cli_doctor.py` → 33 passed（含 4 条新增 lan 用例）；`caplog` 计数**恰一条** WARNING |
| 72.4 安全口径 canonical 与派生同步 | frame §4.19 要素 3/4/5 双档化 + §4.17/§4.17.1（删双监听与 `WS_EXTERNAL_*` 键表、监听模式行加 `lan`）+ AGENTS/CLAUDE 派生副本 + 守卫短语集加 `WS_LAN_NO_AUTH` | `tests/test_security_posture_contract.py`（要素仍 1..6、canonical 段唯一）+ `mkdocs build --strict` 0 warning |
| 72.5 落地与端到端验收 | 本机 `.env`：`WS_HOST=192.168.2.226`、`WS_LAN_NO_AUTH=true`、TLS 键停用；容器内端到端取证 | 见下「端到端证据」 |

### 端到端证据（容器内，以私网 `172.17.0.3` 代替 `192.168.2.226`）

```text
127.0.0.1:9201 -> REFUSED(errno=111)
172.17.0.3:9201 -> OPEN
172.17.0.3:9301 -> REFUSED(errno=111)

ws_manual_probe ws://172.17.0.3:9201 ping
  <- {"type":"hello","version":"0.10.0"}            PASS hello 首帧
  -> {"command":"ping"}
  <- {"type":"ack","command":"ping","run_id":""}    PASS 集合端点 ack

GET /api/status listeners:
  [('http','127.0.0.1',9101,'local',False), ('ws','172.17.0.3',9201,'lan',False)]

日志:
  ws event=started address=172.17.0.3:9201 listener=lan tls=ws
  ws event=exposed host=172.17.0.3 listener=lan auth=none tls=ws cron_push=off
```

（`listener=lan tls=ws` 的 `tls=` 字段为既有日志键、语义是「该 listener 属 WS 传输」，不是「已启用 TLS」；
同一行的 `tls=False` 投影与 `auth=none` 才是明文判据。这一处命名歧义见 Open questions。）

## 门禁实测（补做 retro 时复跑）

```text
pytest -q（PATH 含 node v20.18.1）   → 5518 passed / 17 skipped / 30 deselected / 1 xfailed（0 failed，276s）
ruff check src tests scripts examples → All checks passed
ruff format --check                   → 514 files already formatted
mypy src                              → no issues in 233 source files
bandit -r src/ -ll                    → High/Medium/Low 全 0
mkdocs build --strict                 → 0 warning（4.34s）
```

对照 72.2 交付时的记录：全量 `5466 passed`（当时）→ 本轮 `5518 passed`，增量来自 Epic 71 / 70 的后续批次；
**无新增失败**。

## 教训

- **退役一个配置族 = 硬删除 + 残留键可见性，缺一不可**。只删字段会让老 `.env` 静默失效（用户以为还在用
  `WS_EXTERNAL_HOST`，实际早已不读）；`doctor.retired_key` 那条 INFO 是这次「无害退役」的关键——
  它把「静默不生效」变成「启动前可见」。
- **删代码要连脏基线一起删**。当时全量测试有 5 例 CRLF 断言红，全部来自 `tests/test_setup_ws_external.py`;
  随脚本一起删除后环境红消失。删文件前先确认「它自己在制造门禁噪声」，否则会遗留一条无人认领的恒红。
- **安全口径改动必须 canonical + 派生副本 + 守卫短语集三处同批**。只改 `docs/frame.md` 会被派生副本
  （`AGENTS.md` / `CLAUDE.md`）的旧口径反超，只改代码会被守卫测试以旧短语继续放行。
- **免认证 ≠ 拆防线**。`lan` 保留 Host/Origin 校验，且判据形式是「同一 listener 上两条断言」——
  无 token 拿到 `101`、坏 `Host` 被拒。单边断言（只测能连）证明不了防线还在。
- **需求真源若是不入库文件，事实落点必须搬进仓库内**。`docs/tls-connect-guide.md` 被 `.gitignore`（第 63 行）
  排除、会话中途从工作树消失 ⇒ 72.4 把事实改写进了 `deploy/README.md` 与 `.env.example`，这是正确的降级处置；
  但该页本身的「状态」行因此长期滞后（见残差）。

## 残差与待裁定

- **宿主真机 `netstat` 对账未实测**（唯一未闭合验收项，**已升台账 A75**）：容器内无 `192.168.2.226` 网卡，故以私网地址做同型判据。
  待用户执行：`netstat -ano | findstr :9201`（本地地址应为 `192.168.2.226:9201`，且无 `0.0.0.0:9201` /
  `127.0.0.1:9201` 与 `9301`）+ 客户端 `ws://192.168.2.226:9201` 三处对账。
- **需求真源状态行滞后**：`docs/tls-connect-guide.md` 头部仍写「状态：第一步**未实施**」（与已交付代码矛盾），
  且该页不在 `mkdocs.yml` nav（`mkdocs build --strict` 只给 INFO「pages exist but not in nav」，不是 warning）。
  该文件 gitignored ⇒ 改它不入库、只对本地有效；把它纳进 nav 又会因 CI 不 checkout 该文件而断链。
  **建议**：状态行就地改为「第一步服务端已实施（2026-11-19，Epic 72）；客户端改造与第二步待做」，nav 维持不登记。
- **范围外**（epic 边界已写明，不算残差）：客户端 `aihome-client` 6 处改动；第二步 `wss://` + Bearer token。
- **台账（已登记）**：宿主对账升为 `open-items.md` **A75**（`active`，2026-11-19 用户裁定）。
  四处「活动 N 条」同批 16 → 17：`open-items.md`、`epic-overview.md`（§1.3 与 §1.4-A 两处）、
  `_bmad-output/README.md`、`implementation-artifacts/README.md`——受
  `tests/test_deferred_id_registry.py::test_active_count_declarations_match_the_ledger` 逐处严格比对。

## Open questions

1. 启动日志 `listener=lan tls=ws` 里的 `tls=` 复用既有键表达「WS 传输」，与同一 listener 的
   `tls=false`（未启用 TLS）语义冲突——是否把日志键改名为 `transport=ws`（需同步既有日志解析方）？
2. `lan` 档是否会长期存在？若第二步 `wss://` + token 落地后 `lan` 仅作临时调试入口，
   则「每次启动一条 WARNING」应保留；若成为常态，则考虑按 `DEBUG_MODE` 降级为 INFO。
3. 退役键提示现在只在 `doctor` 里出现；`http-server` 启动路径是否也该打一条一次性 WARNING，
   让「不跑 doctor 的人」也能看到？
