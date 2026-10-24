# Epic 56 · WS 对外入口周期 · Brief

> 立项：2026-10-24，**同日 D1–D7 已全部由用户拍板冻结**（D1 = HTTP 与 WS 完全分离；D2–D7 按提议值冻结）。
> 本文是唯一决策记录；story 拆分见 `epics.md` 与 `stories/`，任一决策变更须经用户并回写本文。

## 背景

现状（Epic 49–55 交付）：HTTP+SSE 是主入口（控制面 + 网页控制台），WS 是订阅/旁观通道；WS 路由（`/api/runs/{run_id}/ws`、`/api/cli/ws`）**挂载在 HTTP 的 ASGI app 里**，与 HTTP 共用回环监听器（默认 `127.0.0.1:8766`），均无认证、无 TLS。外部客户端（IDE 插件、桌面客户端、远程协作）需要经网络访问 HeAgent。**用户拍板（2026-10-24）：HTTP 与 WS 完全分开**——

- **HTTP server**：纯 HTTP+SSE（控制台页 + REST + SSE），回环 only，**不再挂任何 WS 路由**；
- **WS server**：独立 ASGI app、独立配置、独立监听器，**零 HTTP 路由**，是所有 WS 能力的唯一宿主（本机订阅 + 对外访问）。

## 与既有决策的冲突（显性列出，不折中）

| 冲突点 | 既有立场 | 本周期处置 |
|---|---|---|
| Epic 54 D1 | WS 与 SSE「并存」，同 app 同端口 | **取代其拓扑部分**：并存立场不变，但 WS 迁至独立 server；`/api/runs/{id}/ws` 路径不变、**端口迁移**（8766 → 9001，breaking change，文档须写明） |
| Epic 54/55 装配 | WS 路由挂 HTTP app、`cli_hub` 注入 `build_http_app` | **整体迁出**：HTTP app 移除 WS 路由与 `ws_*` 配置（`ws_max_connections` 等迁入新 `WsServerConfig`）；`websockets` 依赖留在 `http` extra 供 WS server 使用 |
| Epic 49 AD-6 | 反向代理部署不在支持范围，forwarded-* 即拒 | 不引入代理依赖；TLS 方案见 D4 |
| AGENTS.md 安全声明 | 入口层非安全边界，OS 沙箱兜底 | **立场不变，不放宽**；对外放大暴露面 ⇒ 期一判据必须含未认证拒绝与限额变异体；对外能提交 run ⇒ Epic 53 沙箱档文档从建议升级为强烈建议 |

## 接缝事实（起草时已知；深勘察留周期会话）

- 完全分离 = 同进程两个 uvicorn server、两个 ASGI app、两份配置：共享的只有注入的**进程内状态**（`HttpRunService`、`CliEventHub`）与 `network/` 同层协议模型；`network/` 依赖边界约束不变
- HTTP app 的三个中间件对非 http scope 放行——分离后 HTTP app 不再收到 WS 升级请求，该缝随之消失；WS server 自建最小中间件栈（认证 / Origin / 访问日志），无静态页无 CSP
- 认证缺口：全库无认证代码；Origin 校验对非浏览器客户端不适用（缺 Origin = 放行），对外防线必须换**认证**
- 凭证真源：用户级 `~/.heagent/setting.md`；token 落用户配置，**禁**项目 `.env` 与代码副本
- 能力缝：Epic 54 D2 显式不做「经 WS 提交 run」；对外入口若只读订阅则远程客户端无生产价值——提交能力是本周期核心新面
- 单用户语义：`HttpRunService` 是「进程内单用户会话」（AD-3，名额按项目）；对外多连接默认共享同一运行状态机
- 生命周期：HTTP 与 WS 两 server 各自有界关停（对齐 `HttpServer.close()` / `close_websockets` 口径），入口层统一编排

## 冻结决策（2026-10-24 用户拍板，变更须经用户）

| # | 决策 | 冻结值 |
|---|------|--------|
| D1 | 拓扑 | **HTTP 与 WS 完全分离**：HTTP server 纯 HTTP+SSE（回环 only，移除全部 WS 路由）；新 WS server 独立 ASGI app + `WsServerConfig`（host/port 独立，默认 `127.0.0.1:9001`），零 HTTP 路由；既有两条 WS 端点迁入（路径不变、换端口） |
| D2 | 能力边界 | WS 能力面：订阅 run 事件 + `cancel`/`ping` + **提交 run**（新命令帧，等价 `POST /api/runs` 语义：名额满回 `run_conflict`，不排队）；配置/项目/会话/对话框**只走本机 HTTP**，WS server 不可达 |
| D3 | 认证 | 静态 token（用户级 setting.md 声明），`Authorization: Bearer` 握手校验，失败未 accept 前 close(1008) |
| D4 | TLS | 原生 TLS 可选（cert/key 路径配置，配齐即 wss）；不配 = 明文 + 启动告警。不引入反向代理依赖 |
| D5 | 监听模式 | **单 WS 监听器按绑定地址切模式**：回环绑定 = 本地模式（Origin 防线 + 无认证，Epic 54/55 本机语义保持）；非回环绑定 = 对外模式（**token 缺失拒绝启动** fail-closed、认证强制、Origin 不适用）。「本机免 token + 对外有 token」同时并存的场景不做——期二双监听另裁 |
| D6 | 并发语义 | 期一**单用户不变**：所有 WS 连接共享同一运行状态机与名额（多客户端看到同一 run 流）；多租户/会话隔离不做 |
| D7 | CLI 旁路归属 | `/api/cli/ws` 随迁移进 WS server（默认本地模式可达）；不随对外模式新增暴露面之外的特殊处理 |

## 期一范围

1. **WS server 骨架**：独立 ASGI app + `WsServerConfig`（自 `HttpServerConfig` 剥离 `ws_*` 旋钮）+ 有界生命周期（start/serve_forever/close 对齐 HttpServer 口径）
2. **迁移**：两条 WS 端点自 HTTP app 迁入 WS server（端点逻辑复用 `ws_server.py`）；HTTP app 移除 WS 路由、`cli_hub` 装配缝与 `ws_max_connections` 配置；端口迁移的 breaking change 写入 deploy/README 与 `docs/frame.md`
3. **认证中间缝**（对外模式）：Bearer token 校验 + 失败 close(1008) + 缺配置拒绝启动（显性失败）
4. **帧协议扩面**：`run` 提交命令帧 + ack（复用 `HttpErrorCode` 与既有错误信封）
5. **TLS 可选装配** + 明文告警
6. **测试与文档**：分离判据（8766 上 WS 升级 404、9001 上无 HTTP API 面）、认证变异体（无 token/错 token/明文告警）、限额、提交冲突、`frame.md` 4.17/4.18 与 AGENTS.md 安全声明同步

## 非功能需求

- **安全**：对外模式认证强制（fail-closed）；明文运行状态必须日志可见；OS 沙箱兜底立场不变——**对外能提交 run ⇒ 沙箱档（Epic 53）文档升级为强烈建议**
- **限额**：WS 连接额度随 `WsServerConfig` 迁移；认证失败限速；检查与登记同一步（2026-09-27 教训口径）
- **兼容**：HTTP/SSE 与本机 HTTP API 契约零改动；**WS 端口迁移是唯一 breaking change**（Epic 54 客户端刚落地，不设兼容窗口，文档写明即可）；`network/` 依赖方向零放宽
- **生命周期**：双 server 有界关停；断线不取消 run（既有立场）

## 验收标准

1. HTTP listener（8766）：WS 升级请求 404；REST / SSE / 静态页 / 控制台 API 行为零改动
2. WS server（9001）：无任何 HTTP API 面（控制台页、静态资源、REST 均不可达）
3. 默认配置（回环绑定）下 Epic 54/55 本机语义保持：可订阅、可续传、可 cancel/ping
4. 非回环绑定 + 无 token ⇒ 拒绝启动；有 token ⇒ 认证强制，无效/缺失 token 握手被拒（1008，未 accept 前）
5. 经 WS 提交 run：事件 seq 单调、`cancel` 等价 DELETE、名额满回 `run_conflict`
6. 对外模式无法触达配置/项目/会话/对话框能力（D2 边界的可执行判据）
7. 明文模式启动有告警日志；TLS 模式握手走 wss
8. `pytest` / ruff / mypy / bandit / `test_architecture_contracts.py` 全绿

## 冻结边界

- 不做：双 WS 监听并存（本机免 token + 对外有 token 同时服务，期二另裁）、多租户/多用户隔离、细粒度权限、反向代理支持、控制台前端切换 WS
- 不改：本机 HTTP/SSE 既有行为、AGENTS.md 依赖方向与 OS 沙箱兜底立场

---

# 期二 · 双 WS 监听并存（2026-10-24 立项，D8–D14 同日由用户拍板冻结）

> 决策来源 = `phase2-proposal.md`（勘察 + 提案）→ **用户 2026-10-24 回复「按推荐的走」**，本表为冻结值。
> 期一 D1–D7 全部继续有效；期二只**扩面**，不改期一任何冻结值（D5 的「期二另裁」由此节闭合）。

## 期二目标

在**同一进程**内再起**一个** WS listener，使「本机免 token」与「对外带 token」**同时**可用：

- **主 listener**：沿用 `WS_HOST` / `WS_PORT`，**期一语义逐字不变**（回环 = 本地模式；非回环 = 对外模式）；
- **对外 listener**（新增，可缺省不启用）：非回环绑定 + token 强制 + TLS 可选；
- 两者共享同一个 `HttpRunService`（run 记录、名额、`cancel` 语义因此天然一致），
  **端点可见性不同**：终端内容（`/api/cli/ws`）**只**出现在本地 listener 上。

## 冻结决策（D8–D14）

| # | 决策 | 冻结值 |
|---|------|--------|
| D8 | 配置面 | **主/副双键**：`WS_HOST` / `WS_PORT`（主 listener，期一语义不变）+ 新增 `WS_EXTERNAL_HOST`（默认 `None` = 不启用）+ `WS_EXTERNAL_PORT`（默认 `9002`）。`WS_EXTERNAL_HOST` 非空即启用对外 listener，且**必须非回环**（回环值 fail-loud）；主 listener 已非回环时再配 `WS_EXTERNAL_HOST` ⇒ fail-loud（两个对外 listener 无意义）。列表式 `WS_BIND` **否** |
| D9 | 端点可见性 | 提交 `/api/runs/ws` 与订阅 `/api/runs/{run_id}/ws` 在**两个** listener 上都注册；CLI 旁路 `/api/cli/ws` **只**在本地 listener 注册，对外 listener 上不注册（客户端拿 403）。**连带收紧**：任何对外 listener 都不提供 CLI 旁路——期一的「`WS_HOST=0.0.0.0` + `WS_CLI_BYPASS_ENABLED=true`」组合起改为跳过旁路并打 `ws event=cli_bypass_skipped reason=external_listener` WARNING |
| D10 | TLS 归属 | 对外 listener 用 `WS_EXTERNAL_TLS_CERT_FILE` / `WS_EXTERNAL_TLS_KEY_FILE`，**缺省继承** `WS_TLS_*`；半配 fail-loud（期一同口径）。这样「本地明文 + 对外 wss」可配，而期一单对外部署的既有配置照旧生效 |
| D11 | 限额 | 订阅额度按 run record 天然共享（无需改动）；提交席位池每个 listener 各 `ws_max_connections` 席（双监听上限 2×N）；认证失败限速每个 listener 独立窗口。**不新增** `WS_EXTERNAL_MAX_CONNECTIONS` |
| D12 | 装配与生命周期 | 新增 `build_ws_servers()` 返回 1–2 个 `WsServer`；`EmbeddedHttpService` 持有 server **列表**。启动顺序 HTTP → 本地 WS → 对外 WS，任一失败**回滚已启动的全部**；关停 HTTP 先（排空在途 run 到终态）再逐个 WS（并行）。公告与日志带 `listener=local|external` 标记（既有事件名不变） |
| D13 | 观测 | 对外 listener 沿用期一 `ws event=exposed host=… mode=external auth=token tls=…` 与 `ws event=plaintext_external`（补 `listener=` 标记）；本地 listener 沿用 `exposure_warning` 判定 |
| D14 | 文档与契约义务 | `docs/frame.md` 4.17/4.18 增双监听拓扑（配置表 +4 键、模式派生表补「主=本地 / 副=对外」行）；`AGENTS.md` 安全声明补双监听口径（立场不变）；`deploy/README.md` 补双监听部署示例；`.env.example` +4 键 + 一行「终端旁路只在本地 listener」；`tests/test_architecture_contracts.py` 钉住「对外 listener 端点集 = {提交, 订阅}」 |

## 期二范围（story 拆分见 `epics.md` 期二节）

1. **配置面与双 listener 装配**（56-5）：Settings 4 键、`WsServerConfig` 增加 listener 标签、
   `build_ws_servers()`、`EmbeddedHttpService` 列表化、CLI `--ws-external-host` / `--ws-external-port`、`.env.example`
2. **端点可见性与双监听安全不变量**（56-6）：对外 listener 仅注册提交 + 订阅；CLI 旁路跳过 + WARNING；
   对外独立 TLS 键与继承；双监听 e2e 判据
3. **文档、契约与质量门**（56-7）：`frame.md` / `AGENTS.md` / `deploy/README.md` / 架构契约 / 全量门禁实测登记

## 期二验收标准

1. **零行为变化**：不配 `WS_EXTERNAL_HOST` 时期二与期一完全等价（既有全部测试零改动全绿）
2. 双监听并存：本地 listener（无 token 可连）与对外 listener（必须 token）**同时**服务；
   同一 run 从两个 listener 订阅拿到**同源**事件（`seq` 单调且一致）
3. 对外 listener 上 `/api/cli/ws` **不可达**（403）；`WS_CLI_BYPASS_ENABLED=true` + 单对外 ⇒ 旁路被跳过且日志可见
4. 配置 fail-loud 四例：`WS_EXTERNAL_HOST` 回环值 / 主 listener 已非回环时再配对外 / 对外缺 token / TLS 半配
5. 提交席位双 listener 独立计数（2×`WS_MAX_CONNECTIONS`），订阅额度仍按 run 共享
6. 启动/关停全有界：任一 listener 起不来 ⇒ 已启动的全部回滚，不留半启动状态
7. `pytest` / `ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` / 架构契约全绿（实测登记）

## 期二冻结边界

- 不做：多租户/多用户隔离、细粒度权限（按 listener / 按端点授权）、反向代理支持、
  `WS_EXTERNAL_MAX_CONNECTIONS`（额度复用 `WS_MAX_CONNECTIONS`）、对外 listener 上的终端旁路
- 不改：期一 D1–D7、本机 HTTP/SSE 行为、`network/` 依赖方向、OS 沙箱兜底立场
