---
title: '56-5 配置面与双 listener 装配'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'bab1dc5c0f6e23f9eb397a6aaf1711803cdf9bc9'
context: []
---

<!-- 交付物与验收边界 = epics.md 期二 56-5 行；冻结决策 D8/D10/D11/D12/D13 见 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 期一只允许**一个** WS listener，其身份由绑定地址决定：`WS_HOST` 回环 ⇒ 本地免 token；非回环 ⇒
对外强制 token。二者不可兼得——想给远程客户端提供有认证的入口，就必须放弃本机免 token 的体验（且本机客户端
也得配 token）。

**Approach:** 引入**第二个 WS listener**（对外），与主 listener 并存。配置面用**主/副双键**：`WS_HOST` /
`WS_PORT` 保持期一语义（主 listener），新增 `WS_EXTERNAL_HOST`（默认 `None` = 不启用）/ `WS_EXTERNAL_PORT`
（默认 `9002`）/ `WS_EXTERNAL_TLS_CERT_FILE` / `WS_EXTERNAL_TLS_KEY_FILE`（缺省成对继承 `WS_TLS_*`）。
装配收口到 `build_ws_servers()`，返回 1–2 个 `WsServer` 与实际生效的 `CliEventHub`；`EmbeddedHttpService`
从「HTTP + 一个 WS」升级为「HTTP + WS 列表」。

**零行为变化红线：** 不配 `WS_EXTERNAL_HOST` 时代码路径与期一逐字等价。

## Boundaries & Constraints

**Always:**
- 主 listener 的构造路径与期一**同一个函数**（`build_ws_server_config`），不复制一份参数映射
- 对外 listener 的 `WsServerConfig` 必须 `mode == "external"`（非回环 + token），否则 fail-loud
- TLS 继承是**成对**的：对外 cert/key 都不设 ⇒ 整对继承 `WS_TLS_*`；只设一半 ⇒ `WsConfigError`
  （绝不 A 的 cert 配 B 的 key）
- 配置矩阵 fail-loud 四例：对外键取回环值 / 主 listener 已非回环时再配对外键 / 对外缺 token / TLS 半配
- 启动顺序 HTTP → 主 WS → 对外 WS；任一失败回滚**已启动的全部**（不留半启动）
- 关停顺序 HTTP 先（排空在途 run 到终态），再并行关所有 WS listener
- 日志与公告带 `listener=local|external` 标记；该标记的取值来自 `WsServerConfig.mode`
  （**不新增** `listener` 字段——`mode` 就是 listener 身份，新增字段只会让两者可能不一致）
- `EmbeddedHttpService.cli_hub` 语义收紧为「**实际挂载**的 hub」：被跳过时返回 `None`

**Never:**
- 不引入列表式 `WS_BIND`（D8 已否）
- 不新增 `WS_EXTERNAL_MAX_CONNECTIONS`（D11：额度复用 `WS_MAX_CONNECTIONS`）
- 不改 `build_ws_server_config` 的既有签名与语义（期一测试零改动）
- 不让 `http-server` 命令意外获得 CLI 旁路（它没有终端轮次可看，显式传 `cli_bypass=False`）
- 不在本 story 改变端点可见性（属 56-6）：本 story 只搭建装配骨架，暂时两个 listener 都按既有规则挂路由

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 默认配置 | 无 `WS_EXTERNAL_*` | 1 个 listener（`mode=local`，9001）；与期一逐字等价 | N/A |
| 期一单对外 | `WS_HOST=0.0.0.0` + token | 1 个 listener（`mode=external`） | N/A |
| 双监听 | `WS_HOST=127.0.0.1` + `WS_EXTERNAL_HOST=0.0.0.0` + token | 2 个 listener：local:9001、external:9002 | N/A |
| 对外键取回环 | `WS_EXTERNAL_HOST=127.0.0.1` | 配置不成立 | `WsConfigError`（回环已由主 listener 承担） |
| 主已对外 + 配对外键 | `WS_HOST=0.0.0.0` + `WS_EXTERNAL_HOST=0.0.0.0` | 配置不成立 | `WsConfigError`（两个对外 listener 无意义） |
| 对外缺 token | `WS_EXTERNAL_HOST=0.0.0.0` 且无 `WS_AUTH_TOKEN` | 配置不成立 | `WsConfigError`（fail-closed 沿用 D5） |
| 对外 TLS 半配 | 只设 `WS_EXTERNAL_TLS_CERT_FILE` | 配置不成立 | `WsConfigError`（不跨对混搭） |
| 对外 TLS 不设 | 主 listener 设了 `WS_TLS_*` | 对外整对继承 | N/A |
| 对外端口未指定 | `WS_EXTERNAL_PORT` 默认 9002 | 沿用端口顺延（显式指定即契约） | 绑定失败 → `WsStartupError` |
| 对外 listener 起不来 | 端口被占且显式指定 | 回滚主 WS 与 HTTP，进程显式失败 | 抛 `WsStartupError` |
| CLI 覆盖 | `--ws-external-host` / `--ws-external-port` | 只影响本次实例，不写回 Settings | N/A |

## Code Map

- `src/heagent/config/__init__.py` — `ws_external_host: str | None`、`ws_external_port: int = 9002`、
  `ws_external_tls_cert_file`、`ws_external_tls_key_file`
- `src/heagent/cli/http.py` — 新增 `build_external_ws_server_config()` / `build_ws_servers()`；
  `build_http_service()` 改用后者；`_serve_web()` 接收列表；`EmbeddedHttpService` 列表化（`ws_servers` /
  `ws_addresses`，保留 `ws_address` 返回主 listener）；`http-server` 加两个 CLI 选项
- `src/heagent/network/ws_host.py` — 日志补 `listener=%s`（取 `config.mode`）；`__all__` 不变
- `.env.example` — 4 键 + 「终端旁路只在本地 listener」一行说明
- `tests/network/test_ws_server.py` — 装配矩阵（`build_ws_servers` 返回 1/2 个、四例 fail-loud、hub 跳过）
- `tests/test_cli_http.py` / `tests/test_cli_http_lifecycle.py` — `_serve_web` 假替身签名同步为列表

## Tasks & Acceptance

**Execution:**
- [ ] `config/__init__.py` — 4 个新字段 + 注释说明「`None` = 不启用」
- [ ] `cli/http.py` — `build_external_ws_server_config` / `build_ws_servers`（含回滚安全的装配顺序）
- [ ] `cli/http.py` — `EmbeddedHttpService` 列表化 + `ws_addresses` + `cli_hub` 语义收紧
- [ ] `cli/http.py` — `--ws-external-host` / `--ws-external-port` 选项与 `http-server` 装配
- [ ] `network/ws_host.py` — 日志 `listener=` 标记
- [ ] `.env.example` — 4 键
- [ ] 测试 — 装配矩阵 + 既有 `_serve_web` 替身同步

**Acceptance Criteria:**
- Given 默认配置，when 构造服务，then `len(ws_servers) == 1` 且 `servers[0].config.mode == "local"`
- Given `WS_EXTERNAL_HOST=0.0.0.0` + token，when 构造，then 2 个 listener，第二个 `mode == "external"`
  且 `port == 9002`
- Given 四个 fail-loud 用例，when 构造，then 均抛 `WsConfigError` 且消息含修复指引
- Given 对外 listener 起不来（端口被占），when 启动，then HTTP 与主 WS 均已关闭（无残留 listener）
- Given `WS_CLI_BYPASS_ENABLED=true` + 单对外，when 构造，then `cli_hub is None` 且日志有
  `cli_bypass_skipped`
- Given 全量 `pytest`（未配 `WS_EXTERNAL_*`），then 除 `_serve_web` 替身签名同步外**零断言改动**

## Verification

**Commands:**
- `pytest tests/network/test_ws_server.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py -q` -- expected: 全绿
- `pytest tests/network -q` -- expected: 全绿
- `ruff check src tests && ruff format --check src tests && mypy src --platform linux && bandit -r src/ -ll` -- expected: 全绿

**实测结果（2026-10-24，容器沙箱 + `.heagent/tmp/py311-venv-linux` 取证 venv）:**
- `pytest tests/network/test_ws_server.py -q` → **36 passed**（含本期新增 12 例装配/配置矩阵）
- `pytest tests/network tests/test_cli_http.py tests/test_cli_ws_wiring.py tests/test_cli_ws_publish.py -q`
  → **505 passed**
- `ruff check src tests` → All checks passed；`ruff format --check src tests` → 343 files already formatted
- `mypy src --platform linux` → Success: no issues found in **174 source files**
- `bandit -r src/ -ll` → Medium 0 / High 0

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成，基线 `bab1dc5`。**未给 `WsServerConfig` 加 `listener` 字段**：`mode`
  （`local` / `external`）已经是 listener 身份的唯一真源，再加一个字段只会让两者可能不一致。
  D12 要求的日志标记因此直接取 `config.mode`（`ws event=started … listener=%s`），
  `event=exposed` / `event=plaintext_external` 同步补标记。
- 装配单一真源 = `build_ws_servers()`：返回 `(servers, hub)`，**hub 也由它创建**（期一在
  `build_http_service` 里建）。这样「跳过旁路」的判定只存在一处（`primary.mode != "local"`），
  不会出现「hub 建了但没挂」的隐性状态。`http-server` 命令显式传 `cli_bypass=False`
  （它没有终端轮次可看），期一行为照旧。
- `EmbeddedHttpService` 接受 `WsServer | tuple[WsServer, ...]`：单 listener（期一形态）继续可用，
  内部统一按元组处理；`ws_address` 保留为「主 listener 地址」，新增 `ws_addresses`。
- 回滚顺序：`_serve_web` 与 `EmbeddedHttpService.start()` 都在任一 WS 启动失败时**先关已起的 WS、
  再关 HTTP**；判据 `test_embedded_service_rolls_back_every_listener_when_the_external_one_fails`
  用「端口可被重新 bind」证明 listener 真关了（不只是标记 closed）。
- 顺手修正一处期一误报：`http-server` 命令层原先对所有 WS listener 套 `exposure_warning`，对
  对外模式会打出「no authentication」——现在按 `config.requires_auth` 分流（`external mode;
  Bearer token required; TLS|PLAINTEXT`）。这与 `WsServer.start()` 的 `event=exposed` 口径一致。
- 既有测试同步（**不是**放宽断言）：`tests/test_cli_http.py` 的 `_serve_web` 替身取
  `ws_servers[0]`（4 处属性断言 + 1 处变量）；`tests/test_cli_http_lifecycle.py` 的替身改为断言
  「非空元组」。
- 端口断言一律配 `http_port_auto_find_attempts=0`：默认开启的自动顺延会让 9001/9002 断言在
  端口被真实占用的机器上漂移。

## Review Triage Log

<!-- 三层自审在 56-7 收口时对期二整体做一次；本期先记实施期自查。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | 提案里的「`WsServerConfig` 增加 `listener` 标签」与 `mode` 语义重叠 | low（真，已简化） | `mode` 是绑定地址的派生只读属性，再加 `listener` 会让「两个字段不一致」成为可能；D12 的日志标记直接用 `mode`（见 Implementation Notes）。契约面判据 `test_cli_bypass_is_skipped_on_an_external_primary_listener` 钉住分流 |
| 2 | `_external_tls_files` 若「对外 cert 独配 + 继承 key」混搭，会拿 A 的证书配 B 的私钥 | medium（真） | 改成**成对**规则（都设或都不设），半配 fail-loud；判据 `test_external_tls_files_must_be_set_as_a_pair` |
| 3 | `build_http_service` 若仍按 `settings.ws_cli_bypass_enabled` 自己建 hub，会与 `build_ws_servers` 的跳过判定分叉 | medium（真） | hub 创建收进 `build_ws_servers`，返回 `(servers, hub)`；`EmbeddedHttpService.cli_hub` 语义 = 「实际挂载的 hub」 |
| 4 | `http-server` 命令若默认继承 `ws_cli_bypass_enabled`，会凭空多出一条旁路 | low（真） | 显式 `cli_bypass=False`；期一该命令从未挂过旁路 |
