---
type: epic
parent: initiative-heagent
covers: ["R10", "R13"]
sources: []
companions: []
after: []
risk: medium
---

# Web 端服务器状态面板（把进程自身状态搬上网页）

> 状态唯一写目标 = 同目录 `tickets/tickets.toml`；本信封只描述范围、缺口与契约。

## Description

网页控制台（`heagent http-server`）目前只能回答「服务是否活着」与「连的是哪个版本」，
对**进程自身的运行状态**一无所知：在途几个 run、上限多少、WS 连了几条、绑在哪个地址、
什么监听模式、沙箱用哪一档、cron 有没有作业、内存占多少、请求错了多少次——这些要么只存在
日志里，要么只有 CLI / `grep` 能看。

本周期新开一条**只读**聚合端点 `GET /api/status`（`/api/health` 的字段封闭契约不动），
把运行态、部署面、依赖态、资源、请求计数五组事实投影成封闭模型，网页端以顶栏徽标 +
懒加载面板消费。

## 能力缺口（2026-11-19 实测）

| 事实 | 现状 | 出口 |
|---|---|---|
| 服务身份（service / version / schema） | 有 | `GET /api/health`（`network/http_protocol.py:133`，字段封闭） |
| 在途 run 数 / 上限 | 有，仅进程内属性 | `HttpRunService.active_runs`（`http_server/service.py:109`）+ `config.max_inflight_runs`：**零出口** |
| run 记录数与终态分布 | 有 | `_RunRecord` 在 `service._runs`：**零出口** |
| WS 连接数（runs / notifications / cli） | 有 | `WsRegistry.connection_count`（`network/event_stream_hub.py:88`）：**零出口** |
| 后台任务条数 | 有 | `GET /api/tasks`（Epic 70 / Story 64.11 已接前端） |
| 绑定地址 / 端口 / listener 模式 / TLS | 有 | 只在启动日志（`ws event=started … listener=local|external tls=…`） |
| 沙箱后端 / 配置写入闸门 | 有 | `settings.sandbox_backend` / `settings.http_console_write_enabled`，仅散落在各项目 `/api/config` |
| provider 池与路由档位 | 有 | `ACTIVE_PROVIDER` / `ROUTING_POOLS`：**零出口** |
| 进程 uptime | **无** | 没有任何地方记录启动时刻 |
| cron 作业与 `last_run` | 有（文件） | 每项目 `.heagent/cron/jobs.json`（`cron/jobs.py:85 list_jobs`）：**零出口** |
| 技能数 / 记忆条目数 | 有 | `SkillStore` / `FactStore`：**零出口** |
| RSS / 线程数 / CPU 时间 | **无采集** | 依赖树无 `psutil`，`src/` 内 `getrusage` / `/proc/self` grep 零命中 |
| 请求计数 / 延迟 / 错误码频次 | **无计数** | `_AccessLogMiddleware`（`http_server/middleware.py:104-142`）只打日志不累加 |

## Outcome

- 浏览器里一眼看到「这台服务器现在怎么样」：模式、uptime、在途 run、连接数、资源占用、错误率。
- 排障不再需要 `grep logs/heagent-*.log`：`/api/status` 与面板给出同一份事实，且字段封闭、无密钥、无绝对路径。
- 状态采集不进热路径：计数是整数自增，资源采样是 stdlib 单次读取，**不新增运行时依赖**。

## Requirements

- R10 (FR10): 为长时间操作提供进度提示 —— 运行态与并发名额此前只有日志与内部属性。
- R13 (FR13): 提供开发环境配置，增强日志 —— 日志承载的运行事实补一个可视化出口。

## Constraints

- **依赖方向**：`network/` 不得 import 运行栈（agent/engine/providers/tools/memory/skills/context/cron/events）与
  `config/`。所有运行态数值由**入口层注入的 source** 提供，形状照抄现成范式
  `TaskProgressSource` Protocol（`http_server/endpoints_tasks.py:82`）+ `RegistryTaskSource`（装配点
  `cli/http.py:372`）。
- **零新增运行时依赖**：资源采样只用 stdlib（Linux `/proc/self/*`，Windows `ctypes`）；平台不支持时字段为
  `null` 并显式标注来源不可用，绝不填 0 冒充。
- **协议安全面**：`StatusResponse` 一律 `extra="forbid"`；**不含**密钥值、base_url、宿主或项目绝对路径、
  traceback。文本字段过 `sanitize_message` 同款净化。端点随 listener 可见性规则注册（对外 listener 上
  token 之后同样可见，故只放「可公开的状态标量」）。
- **热路径纪律**：中间件只做整数自增与一次有界 `deque` append（容量是常量，不是配置键）；不接受在
  `/api/status` 里扫盘、`psutil` 采样或聚合历史。
- **覆盖守卫**：`tests/test_web_endpoint_coverage.py` 对「后端有路由、前端零消费」判红。71.1 落地时该路由由
  API 探索器的预置端点消费（`web/api-console.js` 的 `PRESETS`，其条数由 `tests/test_web_api_console.py`
  钉住，新增路由必须同步），因此**不需要**白名单过渡；71.6 接入状态面板后它仍是消费方。
- **台账与布局**：若状态模型新增 `pub/` 模块，须同步 `tests/test_architecture_contracts.py` 的 pub 白名单与
  `scripts/contract_snapshot.py` 重生成基线；不得为此改 `network/ws_server.py ↔ http_server` 的隔离约束。

## Done when

- `GET /api/status` 返回 200，字段集合与 `StatusResponse` 逐字一致（多余/缺失字段即校验失败）。
- 五组事实齐全：运行态、部署面、依赖态、资源、请求计数；不可得的项为 `null` 且有 `source` 标注解释原因。
- 网页端有顶栏徽标与「服务器状态」面板，懒加载轮询、关闭即停、失败保留上次值并标注离线。
- `tests/test_web_endpoint_coverage.py` 双向绿且白名单无 `/api/status` 残留。
- `pytest tests/test_architecture_contracts.py -q` 绿；覆盖率不低于 87%；`pyproject.toml` 依赖段零 diff。

## Boundaries

- 不做历史趋势 / 时序曲线：没有任何持久化，只有瞬时值，图表会撒谎。
- 不做主机级指标（磁盘、网络带宽、其他进程）：只报本进程。
- 不做告警与推送：状态是拉取式只读视图。
- 不改 `/api/health` 契约（Story 70.2 已消费它，字段封闭是既有承诺）。
- 不改认证与暴露面：HTTP listener 仍只绑回环、无认证、无 TLS。

## 残差（立项时已实测，刻意不扩范围）

- **网页进程不启动 cron 调度器**：`cli/http_console.py::new_loop` 在有会话时会顺带构造
  `CronScheduler` 但**直接丢弃**（`enable_cron=True` 只为拿到 cron 工具面）。因此本 epic **只能**报
  `jobs.json` 里的作业定义与 `last_run`，**不得**报「下次触发时刻」——那是 scheduler 运行态，本进程没有。
- **多项目 `jobs.json` 分散**：cron 存储按项目落盘（`WorkspacePaths.cron_file`）。实测修正：服务端**不知道**
  前端当前选中哪个项目（选择只是本页状态），因此 71.3 报的是**进程工作区**那一份，并在文档与面板文案里如实
  标注；要按项目报需先有「状态请求带项目参数」的协议约定，另立项。
- **node 探针仍无执行者**：`tests/test_http_web_ui.py` 的 `app_probe.js` 以 `shutil.which("node")` 为前置，
  本机与 CI 均无 node ⇒ 71.6 的行为回归实际由静态契约 + 真实 HTTP 冒烟兜底（与 Epic 70 同一残差）。
- **资源采样只覆盖 `/proc` 与 `ctypes` 两条通路**：macOS 走 `ctypes` 分支之外的平台（如 BSD）返回
  `null` + `resource_source: "unavailable"`，不引入第三方依赖去补。

## References

- 协议与端点范式：`src/heagent/network/http_protocol.py`、`src/heagent/network/http_server/endpoints_tasks.py`
- 装配点：`src/heagent/cli/http.py`（两处 `HttpServer(...)` 构造）、`src/heagent/cli/http_console.py`
- 运行态来源：`src/heagent/network/http_server/service.py`（`active_runs` / `_runs`）、
  `src/heagent/network/event_stream_hub.py`（`WsRegistry.connection_count`）
- 部署面来源：`src/heagent/network/exposure.py::is_loopback_host`、`src/heagent/network/ws_host.py::WsServerConfig`
- 请求计数载体：`src/heagent/network/http_server/middleware.py::_AccessLogMiddleware`
- 覆盖守卫：`tests/test_web_endpoint_coverage.py`（Story 70.4）
