---
title: '56-2 对外模式：认证与 TLS'
type: 'feature'
created: '2026-10-24'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '67554d9ecd2405ac688cc6671d0701d977be80fc'
context: []
---

<!-- 交付物与验收边界 = epics.md 56-2 行；冻结决策 D3（认证）/ D4（TLS）/ D5（监听模式）见 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** WS server（56-1 拆分后独立在 9001）与 HTTP 入口同档「无认证、无 TLS」，非回环绑定只打一条
exposure 告警就放行；对外客户端要经网络访问时，等于把一个无凭证的 run 控制面暴露给整个网段。

**Approach:** 单 WS 监听器**按绑定地址切模式**（D5）：回环绑定 = 本地模式，Epic 54/55 语义逐字保持
（Origin 防线、无认证）；非回环绑定 = 对外模式——静态 token **fail-closed**（缺 token 拒绝启动，绝不降级
成「无认证对外」）、`Authorization: Bearer` 握手校验在 **accept 之前**完成（失败 close(1008)）、Origin/Host
防线在对外模式不适用（由认证取代其防线地位）。token 真源 = 用户级 `~/.heagent/setting.md`，项目 `.env` /
系统环境变量**一律不采纳**（发现即告警）。TLS 可选（cert/key 配齐即 wss，只配一半 fail-loud），对外模式
无 TLS 时启动告警。

## Boundaries & Constraints

**Always:**
- 回环绑定行为与 Epic 54/55 **逐字保持**：Origin/Host 防线照旧、无认证、无 TLS 也不告警升级
- 对外模式判定单一真源 = `network/exposure.is_loopback_host`（不另写一套「算不算本地」）
- 认证在 **accept 之前**（D3）：失败 close(1008)、不发错误信封、不泄露 token 校验细节
- 认证比较用常量时间（`hmac.compare_digest`）；token 不出现在日志 / repr / 错误文案
- 认证失败**限速**：按来源地址滑窗计数，超额仍回 1008（不给探测者额外信号），日志留 `auth_throttled`
- token 真源唯一：用户级 `setting.md` 的 `WS_AUTH_TOKEN`；项目 `.env` / 系统 env 里的同名键**不采纳**
  并显式告警（否则仓库作者可以预置一个「攻击者已知」的 token 让对外监听器照单全收）
- TLS：`WS_TLS_CERT_FILE` + `WS_TLS_KEY_FILE` 二者要么都给要么都不给；配齐即 wss（uvicorn ssl 参数）
- 限额/断线/错误信封/依赖边界（`network/` 不导入运行栈与配置）全部不变

**Never:**
- 不做多租户 / 会话隔离 / 细粒度权限 / token 轮换接口 / 反向代理依赖（brief 冻结边界）
- 不做「本机免 token + 对外有 token」双监听并存（期二另裁）
- 不改 HTTP/SSE 与本机 HTTP API 契约；不改 run 提交能力（56-3）、不改文档 4.17/4.18 全量重写（56-4）
- 不新增 `HttpErrorCode`；不给 WS 加 HTTP 式中间件栈

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 回环绑定（默认） | `WS_HOST=127.0.0.1`、无 token | 本地模式：无认证、Origin 防线照旧 | N/A |
| 非回环 + 无 token | `WS_HOST=0.0.0.0`，setting.md 无 `WS_AUTH_TOKEN` | **拒绝启动**（配置构造期 fail-loud） | `ValidationError`/`WsStartupError` → 入口层 ClickException |
| token 为空串 / 全空白 | setting.md 写了 `WS_AUTH_TOKEN:` 或 `WS_AUTH_TOKEN: "   "` | 同「无 token」：对外模式拒绝启动 | 同上 |
| 非回环 + 正确 token | `Authorization: Bearer <token>` | 正常 accept、订阅/命令语义不变 | N/A |
| 非回环 + 缺 Authorization | 无该头 | **未 accept 前** close(1008)，不发信封 | 日志 `event=auth_rejected reason=missing` |
| 非回环 + 错 token | 方案错 / 值错 / 多余空格 | 同上（常量时间比较） | `reason=invalid` / `reason=malformed` |
| 认证失败刷屏 | 同一来源连续失败超阈值 | 仍回 1008；触发后不再做 token 比较，日志 `auth_throttled` | 滑窗归零后恢复 |
| 项目 `.env` 写 `WS_AUTH_TOKEN` | 任意绑定模式 | 不采纳该值；启动时告警「该键只在用户级 setting.md 生效」 | 显式告警，不静默忽略 |
| TLS 只配一半 | 只给 cert 或只给 key | 配置构造期 fail-loud | `ValidationError` → 入口层 ClickException |
| TLS 配齐 | cert+key 均可读 | listener 走 wss；握手按 TLS | 文件不可读 ⇒ 启动失败（`WsStartupError`） |
| 对外模式无 TLS | 非回环、未配 cert/key | 启动 WARNING `event=plaintext_external`（+ stderr 一行） | 明文运行状态必须可见 |
| 认证失败不影响运行 | 认证拒绝任意次 | 不触碰 `HttpRunService` / `CliEventHub` 状态 | 断线不取消运行立场不变 |

## Code Map

- `src/heagent/network/ws_host.py` — `WsServerConfig`（加 `auth_token` / `tls_cert_file` / `tls_key_file` +
  `mode` 派生 + 双 `model_validator`）；`build_ws_app`（对外模式 Origin 防线改 no-op，认证门在 accept 前）；
  `WsServer.start()`（uvicorn `ssl_certfile` / `ssl_keyfile`；明文对外告警）
- `src/heagent/network/ws_auth.py` — **新建**：`parse_bearer`（严格 `Bearer <token>`）、`AuthThrottle`
  （按来源滑窗、有界条目）、常量时间比较；纯逻辑、无 I/O
- `src/heagent/network/ws_server.py` — 两个端点增加 `authorize` 回调（accept 前执行、失败 close(1008)）
- `src/heagent/config/__init__.py` — 新增 Settings 字段 `ws_tls_cert_file` / `ws_tls_key_file`；
  新增**只读属性** `user_ws_auth_token`（直读用户级 setting.md，绕开 env/dotenv 层）
- `src/heagent/config/catalog.py` — `WS_AUTH_TOKEN` 计入「已知键」白名单（它是合法用户级键，不该被
  配置面板报成 `unknown_key`），且**不**成为可写项
- `src/heagent/cli/http.py` — `build_ws_server_config` 接线 token / TLS；项目 `.env` 误写 token 的告警
- `src/heagent/cli/init.py` — 用户级配置模板补一行 `WS_AUTH_TOKEN` 注释示例
- `.env.example` — 新增 `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE`；`WS_AUTH_TOKEN` 只写「用户级 setting.md，
  项目 .env 不采纳」说明行（注释形式，不引导用户写到 .env）
- `docs/frame.md` — 配置表补三行（4.17/4.18 全量重写归 56-4）
- `tests/network/test_ws_auth.py` — 新建：bearer 解析 / 常量时间 / throttle 滑窗与上界 / 配置 fail-closed
- `tests/network/test_ws_server.py` — 对外模式路由与认证门（替身 WS 抓 close code）；TLS 装配源码级判据
- `tests/network/test_ws_e2e.py` — 真实 listener：对外模式无 token 拒绝启动 / 错误 token 拿 HTTP 403

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/network/ws_auth.py` — 新建纯逻辑面（bearer 解析 / throttle / 比较）
- [ ] `src/heagent/network/ws_host.py` — 配置三字段 + `mode` + 双 validator + 认证门 + TLS 装配 + 明文告警
- [ ] `src/heagent/network/ws_server.py` — 两端点加 `authorize` 前门（accept 前）
- [ ] `src/heagent/config/__init__.py` — TLS 两字段 + `user_ws_auth_token` 属性
- [ ] `src/heagent/config/catalog.py` — 已知键白名单纳入 `WS_AUTH_TOKEN`
- [ ] `src/heagent/cli/http.py` — 装配接线 + 项目 `.env` 误写告警
- [ ] `src/heagent/cli/init.py` / `.env.example` / `docs/frame.md` — 三处同步
- [ ] `tests/network/test_ws_auth.py`（新建）/ `test_ws_server.py` / `test_ws_e2e.py` — 判据落地

**Acceptance Criteria:**
- Given `WS_HOST=0.0.0.0` 且 setting.md 无 token，when 启动，then **拒绝启动**且文案说明缺 `WS_AUTH_TOKEN`
  （变异体：空串 / 全空白同判）
- Given 对外模式 + 正确 token，when 带 `Authorization: Bearer <token>` 握手，then 正常订阅与 cancel/ping
- Given 对外模式，when 缺失 / 错误 token，then **未 accept 前** close(1008)（替身 WS 抓 close code；真实
  listener 上客户端拿 HTTP 403）
- Given 回环绑定，when 不带任何认证头，then 行为与 Epic 54/55 逐字一致（既有 e2e 全绿即证）
- Given TLS 配齐，when 真实 listener 启动，then `wss://` 握手成功、明文 `ws://` 握手失败
- Given 对外模式无 TLS，when 启动，then WARNING 日志含 `plaintext_external`
- Given 同一来源连续认证失败超过阈值，when 再连，then 仍 1008 且日志含 `auth_throttled`
- Given 全量 `pytest` / ruff / mypy / bandit / 架构契约，then 全绿

## Verification

**Commands:**
- `pytest tests/network/test_ws_auth.py tests/network/test_ws_server.py tests/network/test_ws_e2e.py -q` -- expected: 全绿
- `pytest tests/network -q` -- expected: 全绿（HTTP/SSE 零回归）
- `pytest -q` -- expected: 全量绿
- `ruff check src tests && ruff format --check src tests && mypy src && bandit -r src/ -ll` -- expected: 全绿

**实测结果（2026-10-24）:**
- `pytest tests/network -q` → **431 passed**
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py` → **3906 passed / 50 skipped / 25 deselected**
- `ruff check src tests` / `ruff format --check src tests` / `mypy src` / `mypy src --platform linux` /
  `bandit -r src/ -ll` → 全绿（bandit Medium 0 / High 0）
- `scripts/quality_gate.py` → 覆盖率 **92.33%**（门限 87%），静态门全绿；唯一失败 = 下方「已知非回归」

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成，基线 `67554d9`（56-1 交付提交）。新增 `network/ws_auth.py`（Bearer 严格解析 /
  `hmac.compare_digest` / 按来源滑窗限速 / 条目有界）；`WsServerConfig` 加 `auth_token`(`SecretStr`)、
  `tls_cert_file`、`tls_key_file` 与 `mode` / `requires_auth` / `auth_secret` / `tls_enabled` 派生 + 双
  `model_validator`（对外模式缺 token、TLS 半配都 fail-loud）；`build_ws_app` 在对外模式把 Origin/Host
  防线改为 no-op 并注入认证门；两个端点在 `accept()` **之前**认证（失败 `close(1008)`、不发信封）。
- token 真源实现为 `Settings.user_ws_auth_token` **只读属性**直读用户级 `setting.md`（刻意不做成
  Settings 字段：字段会进入「env > 项目 .env > 用户 md」优先级链）。`config/catalog.py` 新增
  `USER_ONLY_SETTING_KEYS`，**只对用户层**把 `WS_AUTH_TOKEN` 当已知键（项目 `.env` 里写它仍照常报未知）。
- 失败映射：`WsConfigError`（新增）由命令层转 `ClickException`、默认 CLI 经
  `embedded_http_error_message` 转一行文案；入口层公告按模式/TLS 输出（`_ws_url` / `_ws_access_note`）。
- 实施级取舍（不影响冻结边界）：① **不加** `--ws-tls-cert/--ws-tls-key` CLI 选项——TLS 是部署级配置，
  `WS_TLS_*` 已覆盖，加选项只会扩大命令面（若后续判定需要，属配置面变更而非本 story 遗漏）；
  ② 测试用自签证书入库（`tests/fixtures/ws_tls/`，附 README 说明「非凭证 + 为何入库」），因为
  `cryptography` 不是项目依赖、用 `openssl` 现场生成会把判据变成可跳过项。
- 实测（本机，`PYTHONPATH=/workspace/src` + `.heagent/tmp/py311-venv-linux`）：见上方 Verification 的实测结果。

## Review Triage Log

<!-- 2026-10-24 step-04。运行时无子代理，经用户裁定由主会话自审（选项②）：三层指令
（blind-hunter / edge-case-hunter / verification-gap）逐层执行，独立性弱化已如实注明。
56-2 与 56-3 同轮审查，跨 story 的发现按**缺陷所在文件**归属（提交端点相关记 56-3）。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | `USER_ONLY_SETTING_KEYS` 若对**所有**扫描来源生效，项目 `.env` 里的 `WS_AUTH_TOKEN` 会被诊断面板当成合法键——与「写了不生效」的事实矛盾，等于替错误配置打掩护 | medium（真） | 读 `_unknown_keys` 确认它遍历全部 `scans` → **patch**（放行只对 `ConfigSource.GLOBAL_SETTING` 生效；新增 `test_user_level_token_in_the_project_env_is_still_reported_as_unknown`，变异：改回全局放行即红） |
| 2 | Pydantic 校验错误从 `build_ws_server_config` 原样上抛 ⇒ `heagent http-server --ws-host 0.0.0.0`（无 token）吐 traceback | medium（真） | 命令层未包 try → **patch**（新增 `WsConfigError` + ClickException + `embedded_http_error_message` 映射；CLI 级三例判据） |
| 3 | 本地模式配了 token 却静默不生效（用户以为已受保护） | low（真） | D5 冻结「回环 = 无认证」⇒ 行为不改，但**必须可见** → **patch**（启动 WARNING `auth_token_ignored`，caplog 判据） |
| 4 | 对外模式仍打 `exposure` 文案「no authentication / not a production security boundary」 | low（真） | 文案与事实不符 → **patch**（对外模式改打 `event=exposed mode=external auth=token tls=ws|wss`） |
| 5 | TLS 文件不可读（配齐但路径错）无判据 | low（真） | 读 `start()` 确认 OSError 被映射为 `WsStartupError` → **patch**（`test_ws_server_with_unreadable_tls_files_fails_loud`） |
| 6 | 新测试的假 token 触发 ruff S105/S106/S107 共 12 条红，而测试目录既有策略已放宽 S101/S104/S108 | low（真） | `ruff check` 实测 → **patch**（`ruff.toml` tests per-file-ignores 增 S105-S107，理由行注明「测试里的假 token 是正文」） |
| 7 | 浏览器 WebSocket API 无法自定义请求头 ⇒ 对外模式浏览器客户端无法认证 | low（真·文档缺口） | 设计不可改（D3 只认握手头）→ **文档**（`frame.md` 认证行写明「对外模式不支持浏览器直连；本机控制台走 HTTP 不受影响」） |
| 8 | 认证失败限速以来源 IP 为键：NAT 后多客户端共享计数，一个客户端的失败会暂时挡住同 NAT 其他人 | low（驳回） | 限速只在「同源 60s 内连错 10 次」后生效、一次成功即清零；改按 token 指纹计数会让暴力枚举完全绕过限速（本末倒置） |
| 9 | `Settings.user_ws_auth_token` 每次访问重读 `setting.md` | low（驳回） | 只在启动装配时读一次；加缓存会造出「改配置不重启也生效」的错觉，与其它配置项的启动期语义不一致 |
| 10 | 对外模式跳过 Host/Origin 后等于少一层纵深防御 | low（驳回） | 冻结决策 D5 明文规定「Origin 不适用」；对外模式的实际客户端不携带浏览器同源语义，Host 白名单只会把合法连接全拒掉；防线地位由 token 取代且已在 `frame.md` 与 brief 记录 |

## 已知非回归

- `tests/test_cli_http_lifecycle.py` 的 3 条「端口已释放」断言（`probe.bind(("127.0.0.1", port))`）在本机
  环境**恒红**：把 HEAD 导出到 `.heagent/tmp/head_src2` 用同一解释器复跑，结果完全一致（3 failed / 7 passed）
  ⇒ 环境产物（WSL2 端口回收延迟），与本 story 无关。
