---
title: 'Story 73.2 `heagent tls` 命令族'
type: feature
ticket: 2
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
  - 'src/heagent/cli/tls_cmd.py'
  - 'scripts/gen_ws_cert.py'
  - 'src/heagent/cli/console.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 签发、轮换、指纹导出、一致性校验今天分散在一次性脚本与人工 `openssl` 命令里；
「pin 是多少」「这份证书还对不对」没有唯一答案来源，运维只能靠记忆与临时命令。

**Approach:** 新增 `heagent tls {init, issue, rotate-key, fingerprint, verify}` 命令族，把材料管理收成
五个动词；`scripts/gen_ws_cert.py` 保留为薄包装（迁移期），文件头指向新命令。

## Boundaries & Constraints

**Always:**
- `init` 幂等且保守：材料目录已有 `ca.pem`/`identity.key` 时不覆盖，需 `--force` 才重建（且先把旧材料挪进 `backup-<stamp>/`）。
- `issue` **复用** `identity.key`（pin 不变）；`--days` 默认 30；`--san` 可多次追加；缺省 SAN 从当前
  `WS_HOST` 推导并并入既有默认集合（`127.0.0.1` / `::1` / `localhost` / `heagent.local`）。
- `rotate-key` 是唯一改变 pin 的动作：必须打印 `old` / `new` 两个指纹，并提示「双 pin 过渡」与
  「重发安装包」，且要求显式 `--yes`（交互确认或旗标），不得静默。
- `fingerprint` 支持 `--format text|json|pin`：`text` = 四段人读（`spki_sha256` / `short_fingerprint` / `not_after` / `san`）；`json` = 供构建流水线；`pin` = `sha256/<base64(SPKI-SHA256)>`（OkHttp 风格，客户端可直接拷进资源）。三种格式的哈希必须逐字一致。
- `verify` 校验三件事并把失败项逐条列出（叶由本 CA 签发 / 叶公钥 == `identity.key` / 到期余量 > 0）。

**Never:**
- 不把 `ca.key` / `identity.key` 内容打到任何输出面（只报路径、指纹、有效期）。
- 不在宿主缺 `openssl` 时静默降级：报「需在容器内执行」并给容器命令（既有先例）。
- 不新增 `src/heagent/cli/*.py` 之外的落点，也不改 `cli/__init__.py`（永不放 import）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| INIT_FRESH | 空目录 | 生成 `ca.pem`/`ca.key`/`identity.key`/`openssl-leaf.cnf`，打印 pin 与后续命令 | 无 |
| INIT_EXISTING | 已有材料、无 `--force` | 不改动任何文件，退出码非 0 | 消息点名 `--force` |
| ISSUE_REUSE | 已有 `identity.key` | 新 `cert.pem` 公钥 == `identity.key`，pin 与上次相同 | 无 |
| ISSUE_SAN | `--san 10.1.2.3` | SAN 列表含该 IP，旧 SAN 保留 | 无 |
| ROTATE_KEY | `--yes` | 生成新 `identity.key`，pin 变化，打印 old/new 与双 pin 文案 | 无 |
| ROTATE_NO_CONFIRM | 无 `--yes` 且非交互 | 退出码非 0，不改文件 | 消息点名 `--yes` |
| FINGERPRINT | 任意有效材料 | 四段输出，`short_fingerprint` 12 字符 | 无 |
| FINGERPRINT_FORMATS | `--format` 三值 | `text`/`json`/`pin` 三种形态同一哈希；`pin` 形如 `sha256/…` | 未知格式退出码非 0 |
| VERIFY_BROKEN | 叶与 key 不配对 | 逐条列出失败项，退出码非 0 | 不抛 traceback |
| NO_OPENSSL | `shutil.which("openssl")` 为 None | 提示「需在容器内执行」+ 示例命令 | 退出码非 0 |

</intent-contract>

## Code Map

- `src/heagent/cli/tls_cmd.py`（新增）— `tls_group` + 五个 `@tls_group.command`；openssl 调用复用
  `scripts/gen_ws_cert.py` 里已验证的参数形态（`x509 -req -CA … -extfile … -extensions v3_req`）。
- `src/heagent/cli/console.py` — 注册 `tls_group`（`cli.add_command`），保持 `cli/__init__.py` 空壳。
- `scripts/gen_ws_cert.py` — 文件头加迁移说明；`issue_leaf` 改为调用 `tls_identity`+复用 `identity.key`
  （与 73.1 同批），保留旧参数以兼容既有手工流程。
- `tests/test_cli_tls.py`（新增）— 用 `tmp_path` + 真实 openssl（容器内可用）覆盖上表；
  无 openssl 环境 skip 并给出原因。
- **必须同步（否则红）**：`tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned`
  的字母序白名单加入 `tls_cmd`（位于 `terminal` 与 `wiring` 之间）；`docs/frame.md` 的 cli 子模块表与目录树同步。

## Evidence（开工前取证，交付后回填）

- 已实测：容器内 `openssl version` 可用（`/usr/bin/openssl`）；宿主 Windows 无 openssl，既有脚本已要求容器内执行。
- 已实测：`heagent --help` 的子命令由 `cli/console.py` 的 group 注册，`http-server` 在 `cli/http.py:494` 用 `@click.command` 声明后由 console 挂载。
