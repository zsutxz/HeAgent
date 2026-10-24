# Epic 56 期二 · 双 WS 监听并存 · 决策提案（待用户拍板）

> 起草：2026-10-24 16:58 CST（本机实测 `TZ=Asia/Shanghai date`）。
> 状态：**提案，未冻结**。用户逐条拍板后并入 `brief.md` 决策表（D8 起）并拆 story。
> 边界来源：`brief.md` D5 冻结值「『本机免 token + 对外有 token』同时并存的场景不做——期二双监听另裁」，
> 以及 `epic-56-retro-2026-10-24.md` A4（defer，下一周期立项时裁）。

## 0. 一句话结论

期二 = 在**一个进程**内再起**一个** WS listener：主 listener 保持期一语义（回环 ⇒ 本地模式 / 非回环 ⇒ 对外模式），
新增的**对外 listener**（非回环、token 强制、TLS 可选）与之并存，两者共享同一个 `HttpRunService`（因此订阅额度、
run 记录、`cancel` 语义天然一致），但**端点可见性不同**：终端内容（`/api/cli/ws`）**只**出现在本地 listener 上。

## 1. 接缝事实（读代码核实，非推测）

| # | 事实 | 证据位置 |
|---|---|---|
| S1 | 订阅额度**按 run record 计**，不是按端点/按 listener ⇒ 两个 listener 共享同一 run 时额度天然共享 | `network/ws_server.py::_prepare_subscription` → `record.try_add_ws_subscriber(queue, max_connections)` |
| S2 | 提交端点席位池 `_SubmissionSlots` 是**每个端点实例一份** ⇒ 每个 listener 各一份（2 × `ws_max_connections`） | `network/ws_server.py::build_runs_collection_endpoint` 内 `slots = _SubmissionSlots(max_connections)` |
| S3 | 认证门与限速窗口挂在 **app** 上（一个 app = 一个 listener = 一份窗口） | `network/ws_host.py::build_ws_app` 内 `AuthThrottle()` |
| S4 | 监听模式纯由绑定地址派生（`mode` / `requires_auth` 是 `WsServerConfig` 的只读属性），对外模式缺 token 在**构造期**就 fail-loud | `network/ws_host.py::WsServerConfig._validate_external_mode` |
| S5 | 入口装配只有两处 `WsServer(...)`：`build_http_service`（默认 CLI 内嵌）与 `http-server` 命令 | `cli/http.py:394`、`cli/http.py:622` |
| S6 | `WS_*` 已整体归入 catalog 排除组「监听面（只读）」⇒ 新增 `WS_EXTERNAL_*` **无需**改分类规则 | `config/catalog.py::EXCLUSION_GROUPS` `patterns=("HTTP_*", "WS_*")` |
| S7 | 端口顺延函数被 HTTP/WS 共用，且「显式指定 = 契约（冲突 fail-loud）」 | `cli/http.py::_resolve_listener_port` |
| S8 | 同进程多 uvicorn server 已是既成形态（HTTP + WS 两个），第三个不引入新机制 | `cli/http.py::_serve_web` / `EmbeddedHttpService` |

## 2. 待拍板决策（D8–D14）

### D8 配置面 —— 推荐：主/副 listener 双键，不改既有键语义

| 键 | 默认 | 语义 |
|---|---|---|
| `WS_HOST` / `WS_PORT` | `127.0.0.1` / `9001` | **主 listener**，期一语义**逐字不变**（回环=本地模式；非回环=对外模式） |
| `WS_EXTERNAL_HOST` | `None`（不启用） | 非空 ⇒ 启用**对外 listener**；值**必须非回环**，回环值 ⇒ 启动期 fail-loud |
| `WS_EXTERNAL_PORT` | `9002` | 对外 listener 端口；未显式指定时沿用端口顺延（S7 同口径） |

- 主 listener 已是非回环（期一单对外部署）时再配 `WS_EXTERNAL_HOST` ⇒ **fail-loud**（两个对外 listener 无意义，
  且会让「哪个是主」变成运维猜谜）。
- 默认值 ⇒ **零行为变化**：不配 `WS_EXTERNAL_*` 时期二与期一完全等价。
- 被否备选：`WS_BIND=127.0.0.1:9001,0.0.0.0:9002` 列表式（少两个键，但要改既有键语义 + 解析 + 错误定位变差）。

### D9 端点可见性 —— 推荐：终端旁路只在本地面

| 端点 | 本地 listener | 对外 listener |
|---|---|---|
| `WS /api/runs/ws`（提交 run） | ✅ | ✅（token 后） |
| `WS /api/runs/{run_id}/ws`（订阅 + cancel） | ✅ | ✅（token 后） |
| `WS /api/cli/ws`（终端观众席） | ✅（开关开时） | ❌ **不注册**（客户端拿 403） |

理由：`/api/cli/ws` 推的是**终端里那一轮** run 的实时事件（工具调用参数与结果，可能含文件内容）。它存在的
初衷是「本机观众席」；把它挂到对外 listener 等于把终端内容投递到网络，token 只是延迟风险不是消除风险。

**连带收紧（需明确同意）**：期一允许 `WS_HOST=0.0.0.0`（单对外）+ `WS_CLI_BYPASS_ENABLED=true`，此时旁路在
对外 listener 上。期二起改为：**任何对外 listener 都不提供 CLI 旁路**，命中时启动打
`ws event=cli_bypass_skipped reason=external_listener` WARNING（不是静默关闭）。这是**行为收紧**，不是 breaking
（既有的 `ws_cli_bypass_enabled` 仍生效于本地 listener）。

### D10 TLS 归属 —— 推荐：对外可独立配置，缺省继承

- 对外 listener 用 `WS_EXTERNAL_TLS_CERT_FILE` / `WS_EXTERNAL_TLS_KEY_FILE`；未设则继承 `WS_TLS_*`。
- 典型部署因此可以：本地 listener 明文（回环，浏览器连 `ws://127.0.0.1:9001` 不碰证书），对外 listener wss。
- 半配（只给 cert 或只给 key）⇒ fail-loud，与期一同口径。
- 被否备选：完全共用 `WS_TLS_*`（少两个键，但「想要对外 wss、本地明文」做不到，而这正是双监听的主要动机）。

### D11 限额 —— 推荐：订阅额度共享、提交席位与认证限速按 listener 各自一份

- 订阅额度：天然共享（S1），无需改动。
- 提交席位池：每个 listener 各 `ws_max_connections` 席（S2），即双监听上限 2×16。不新增键。
- 认证失败限速：每个 listener 独立窗口（S3），保持期一实现不动。
- 不新增 `WS_EXTERNAL_MAX_CONNECTIONS`：多一个键就要多一份「配错了怎么办」的语义，收益不足。

### D12 装配与生命周期 —— 推荐：`EmbeddedHttpService` 持有 server 列表

- 新增 `build_ws_servers(settings, ...) -> tuple[WsServer, ...]`（1 或 2 个），`build_http_service` 与 `http-server`
  都改用它；`EmbeddedHttpService.__init__(http, ws_servers, *, cli_hub)`。
- 启动顺序：HTTP → 本地 WS → 对外 WS；任一失败**回滚已启动的全部**（沿用现有「不留半启动」纪律）。
- 关停顺序：HTTP 先（排空在途 run 到终态），再逐个 WS（并行 gather）——颠倒会让订阅者错过终态事件。
- 公告逐条打印，前缀区分：`[ws] listening on ws://127.0.0.1:9001 (local mode; no authentication)` /
  `[ws] listening on wss://0.0.0.0:9002 (external mode; Bearer token required; TLS)`。
- 日志加 `listener=local|external` 标记，`ws event=started` 等既有事件名不变。

### D13 观测与文案

- 对外 listener 的 exposed 告警沿用期一 `ws event=exposed host=… mode=external auth=token tls=…`；
  本地 listener 仍是 `exposure_warning`（回环无告警 / 非回环告警）。
- 明文对外：`ws event=plaintext_external` 不变（现在带 `listener=external`）。

### D14 文档与契约义务

- `docs/frame.md`：4.17/4.18 增「双监听拓扑」小节（配置表补 4 键、模式派生表补「主=本地 + 副=对外」一行）。
- `AGENTS.md` 安全声明：补一句「双监听并存时对外 listener 的认证/限额/TLS 与其专属端点面」，立场不变。
- `deploy/README.md`：双监听部署示例（含证书与 token 位置）。
- `.env.example`：四键 + 一行「终端旁路只在本地 listener」说明。
- `tests/test_architecture_contracts.py`：钉住「对外 listener 端点集 = {提交, 订阅}」（不含 CLI 旁路路径）。

## 3. Story 拆分提案（56-5 → 56-6 → 56-7）

| Story | 名称 | 交付物 | 验收要点（可执行） |
|---|---|---|---|
| 56-5 | 配置面与双 listener 装配 | Settings `WS_EXTERNAL_*` × 4、`WsServerConfig` 增加 `listener` 标签、`build_ws_servers()`、`EmbeddedHttpService` 列表化、CLI `--ws-external-host/--ws-external-port`、`.env.example` | 不配 `WS_EXTERNAL_HOST` 时全量既有测试零改动全绿；配置矩阵（回环/非回环/缺 token/主非回环+副配置）四例 fail-loud 或放行判据；双 listener 各自公告与 `listener=` 日志 |
| 56-6 | 端点可见性与双监听安全不变量 | 对外 listener 仅注册提交 + 订阅；CLI 旁路跳过 + WARNING；对外 listener 独立 TLS 继承逻辑；双监听 e2e | 本地（无 token）与对外（token）同时可连；同一 run 两个 listener 订阅 seq 同源；对外打 `/api/cli/ws` ⇒ 403；`WS_CLI_BYPASS_ENABLED=true` + 单对外 ⇒ 跳过旁路并告警；提交席位 2×16 独立计数 |
| 56-7 | 文档、契约与质量门 | `frame.md` / `AGENTS.md` / `deploy/README.md` / 架构契约 / 全量门禁实测 | 契约测试钉端点集；`pytest` / `ruff check` / `ruff format --check` / `mypy src`（+`--platform linux`）/ `bandit -r src/ -ll` / `scripts/quality_gate.py` 全绿并登记实测数字 |

## 4. 需要用户回答的最小问题集

1. **D8 配置键形态**：接受 `WS_EXTERNAL_HOST` / `WS_EXTERNAL_PORT`（推荐），还是要列表式 `WS_BIND`？
2. **D9 端点可见性**：接受「对外 listener 不提供 `/api/cli/ws`」并连带收紧期一的单对外 + 旁路组合（推荐）？
3. **D10 TLS**：接受 `WS_EXTERNAL_TLS_*` 缺省继承 `WS_TLS_*`（推荐），还是共用一套？
4. **全局**：是否按上述 56-5/56-6/56-7 顺序与命名开工？
