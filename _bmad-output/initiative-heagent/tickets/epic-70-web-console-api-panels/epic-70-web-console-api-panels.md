---
type: epic
parent: initiative-heagent
covers: ["R10"]
sources: []
companions: []
after: []
risk: low
---

# Web 控制台 API 面板（把 9101 的能力搬上网页）

> 状态唯一写目标 = 同目录 `tickets/tickets.toml`；本信封只描述范围、缺口与契约。

## Description

HTTP listener（默认 `127.0.0.1:9101`）已提供 18 条路由，网页控制台只消费了其中的一部分，
剩余只读能力**有后端、无界面**；且网页端没有任何「对任意端点发起请求」的入口，用户要看
原始响应只能开 DevTools 手敲 `fetch`。

本周期把未消费的只读能力接进界面（任务进度、服务状态与进程会话快照），补一个同源
**API 探索器**承载「操作任意已存在端点」，最后用一条契约测试把「后端路由 ↔ 前端消费」的
覆盖关系钉死，防止后续新增端点再次静默无人消费。

## 能力缺口（2026-11-19 实测，`src/heagent/web/app.js` 对 `network/http_server/app.py`）

| 端点 | 网页端现状 |
|---|---|
| `GET /api/health` | 已消费，但只判 `status === "ok"`，`service` / `version` / `schema_version` 未展示 |
| `GET/POST /api/projects` | 已消费 |
| `PATCH/DELETE /api/projects/{id}` | 已消费 |
| `GET/POST /api/projects/{id}/sessions` | 已消费 |
| `GET/PATCH/DELETE /api/projects/{id}/sessions/{sid}` | 已消费 |
| `POST /api/projects/{id}/runs` | 已消费 |
| `GET /api/runs/{id}/events`（SSE） | 已消费（`EventSource`） |
| `DELETE /api/runs/{id}` | 已消费（取消） |
| `GET/PUT /api/projects/{id}/config` | 已消费 |
| `POST /api/dialogs/pick-directory` | 已消费（目录选择） |
| **`GET /api/tasks`** | **零消费**（Story 64.11 后端已交付，前端从未接入） |
| **`GET /api/tasks/{task_id}`** | **零消费** |
| **`GET /api/session`** | **零消费** |

另一处缺口不是端点而是**入口**：网页端没有「输入方法 + 路径 + body 并看回原始响应」的地方
（对应上一轮用户诉求「我在网页端怎么输入 GET 的 url」）。

## Outcome

- 网页端能看到后台任务进度（列表 + 单条），运行中自动刷新、全终态自动停。
- 顶部状态条展示服务名与版本（版本号只来自后端下发）与当前进程会话快照。
- 网页端能对任意**已存在**端点发起同源请求并看到状态码、耗时与响应体；写方法有二次确认。
- 契约测试保证「新增 HTTP 路由未接入网页端」会变红，而不是靠人记得。

## Requirements

- R10 (FR10): 为长时间操作提供进度提示 —— 任务进度此前只有 API 与 CLI 出口，网页端零消费。

## Constraints

- `web/` 仍是纯静态资源、零 heagent 导入；`network/` 不得导入运行栈。
- 不引入第三方前端资源与内联脚本/样式；CSP 保持 `script-src 'self'` / `connect-src 'self'`，**不得放宽**。
- 不使用 `innerHTML` 渲染任何接口返回内容（`tests/test_http_web_ui.py` 现有排除性断言继续生效）。
- 全部请求同源；不新增 CORS。
- 不新增后端端点（探索器只调用已存在的路由）；如需只读投影只在网络层加类型化视图。
- 覆盖率不低于 87%；`tests/test_architecture_contracts.py` 与 `tests/test_http_web_ui.py` 全绿。

## Done when

- `GET /api/tasks` / `GET /api/tasks/{task_id}` / `GET /api/session` 三条路由在网页端各有可见出口。
- 网页端有同源 API 探索器，可对上述任意路由与既有写路由发起请求并看到状态码/耗时/JSON。
- 覆盖守卫测试存在且能点名：删掉一条前端调用会红、新增路由未接入会红。
- 静态契约（无第三方资源、无内联脚本、无 `innerHTML`）与 node probe 行为回归全部保持绿。

## Boundaries

- 不做 WS 侧面板（订阅通道已有 SSE 与控制台内行为；`/api/cli/ws`、`/api/notifications/ws` 属终端/推送面，不在网页端暴露）。
- 不做「运行历史列表」：后端当前没有 `GET /api/runs` 列表端点，新增它属于新能力而非「把已有能力搬上网页」。
- 不改认证与暴露面：HTTP listener 仍只绑回环、无认证、无 TLS。
- 不做移动端适配重排（沿用现有响应式规则）。

## 残差（2026-11-19，刻意不扩范围）

- **node 探针没有执行者**：`tests/test_http_web_ui.py` 的 `app_probe.js` 行为回归以 `shutil.which("node")`
  为前置，本机无 node、`.github/workflows/ci.yml` 也没有 `setup-node` ⇒ 那 34 例实际一直是 skip。
  本 epic 的三个面板因此只由静态契约与真实 HTTP 冒烟覆盖；要闭环需单独立项（CI 装 node，或把探针场景
  改写成 Python 侧可执行），不塞进本 epic。
- **`GET /api/session` 在控制台语境里近乎静态**：`service.py` 只对「无项目归属」的运行写
  `_current_run_id`，而控制台运行一律走 `POST /api/projects/{id}/runs` ⇒ 徽标恒显示「暂无运行」。
  这是该端点的既有语义（R3/I13 要求逐字不变），本 epic 选择如实展示而不改后端。

## References

- 路由真源：`src/heagent/network/http_server/app.py`（HTTP）、`src/heagent/network/ws_host.py`（WS）
- 静态契约与前端行为回归：`tests/test_http_web_ui.py`（含 `tests/fixtures/js/app_probe.js`）
- 任务进度后端：`src/heagent/network/http_server/endpoints_tasks.py`（Story 64.11）
- 进程会话快照：`src/heagent/network/http_server/service.py::session_snapshot`
