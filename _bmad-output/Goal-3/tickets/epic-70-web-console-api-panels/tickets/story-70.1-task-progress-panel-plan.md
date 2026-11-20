---
title: 'Story 70.1 网页端任务进度面板'
type: feature
ticket: 1
created: '2026-11-19'
status: done
baseline_revision: '329311d'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: []
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/web/index.html'
  - 'src/heagent/web/app.js'
  - 'src/heagent/web/styles.css'
  - 'src/heagent/network/http_server/endpoints_tasks.py'
  - 'src/heagent/network/http_server/app.py'
  - 'tests/test_http_web_ui.py'
  - 'tests/fixtures/js/app_probe.js'
---

## Intent

**Problem:** 后台任务进度（上下文压缩等）已有只读端点 `GET /api/tasks` / `GET /api/tasks/{task_id}`
（Story 64.11，`endpoints_tasks.py`），但网页端从未消费 —— 用户在浏览器里完全看不到「后台还在做什么」，
只能开 DevTools 手敲 `curl`/`fetch`。

**Approach:** 在前端新增一个只读「任务」视图，零后端改动：

1. 数据面：`GET /api/tasks` 取列表（后端已按 `updated_at` 降序、上限 `MAX_TASK_LIST_ENTRIES`），
   `GET /api/tasks/{task_id}` 取单条（未知 id 回 404 `not_found`，message `no such task`；**不是**
   `unknown_task` —— 端点复用通用码，别在文档或客户端里硬编码那个名字）。
2. 轮询面：列表里存在 `pending` / `running` 时按固定间隔（建议 2s）重取；全为 `completed` / `failed`
   或列表为空时**停止轮询**（不制造空转请求）。页面切到后台（`document.hidden`）时暂停。
3. 渲染面：一律 `textContent` / `createElement`；`message` 是后端有界文本，但**不得**走 `innerHTML`
   （`tests/test_http_web_ui.py` 有排除性断言）。
4. 状态面：空列表显示「当前没有后台任务」；请求失败显示错误码（复用既有 `describeError` 路径），
   不静默吞掉。

## 判据

- 静态契约：`index.html` 含任务视图容器与空态文案；`styles.css` 新增样式无内联 style；无第三方资源。
- 行为回归（`tests/fixtures/js/app_probe.js` + node）：
  - 注入两条任务（一 running、一 completed）→ 列表按后端顺序渲染、`percent` 可见；
  - 轮询：running 存在时下一次 tick 会重取；全终态后 tick 不再触发；
  - `GET /api/tasks/{id}` 回 404 时显示 `unknown_task` 文案；
  - 500 时显示通用失败文案且不清空已渲染内容。
- 后端零 diff：`git diff --stat src/heagent/network/` 为空。

## 落点

- `src/heagent/web/index.html`（视图容器、空态、状态行）
- `src/heagent/web/app.js`（取数、轮询启停、渲染）
- `src/heagent/web/styles.css`（样式）
- `tests/test_http_web_ui.py`（静态契约 + probe 场景）
- `tests/fixtures/js/app_probe.js`（新增场景分支）

## 风险

- 轮询与既有 SSE 流并存：`EventSource` 已占用一条连接，轮询是普通 GET（走连接池），不冲突；
  但**必须在全终态时停轮询**，否则是一个没人关的定时器。
- 若新增 JS 文件（而非写进 `app.js`），需同步 `_WEB_ASSETS` 白名单与静态契约测试 —— 优先写进
  `app.js`，避免多开一条资源面。

## 评审（2026-11-19）

| 判据 | 证据 | 结论 |
| --- | --- | --- |
| 静态契约：容器 / 空态 / 无内联 style / 无第三方资源 | `tests/test_web_tasks_panel.py`（源码级契约，49 例） | 满足 |
| 行为：两条任务按后端顺序渲染、`percent` 可见 | `tests/fixtures/js/panels_probe.js` case `tasks-list` → `TestTasksPanelProbe`（node） | 满足（本轮补：此前只有静态） |
| 行为：存在 `running` 时下一轮重取、全终态后不再排程 | probe `first.timers=1` / `afterTerminal.timers=0` | 满足 |
| 行为：详情 404 文案 | probe → `not_found: no such task` | 满足；本 plan 原写 `unknown_task` 有误（端点复用通用码），以实测为准 |
| 行为：列表 500 不清空已渲染内容 | probe `afterFailure`（`rows=2` / `state=failed` / 仍排程） | 满足 |
| 后端零 diff | `network/http_server/assets.py` +3（新脚本进白名单），路由与端点零改动 | 修正口径：白名单是新增静态资源的必需面，本条按「路由/端点零 diff」判 |

**评审补充**：本机无 node 时该 epic 只有静态契约（作者原判断），本轮装上 node（20.18.1）后补齐
行为探针，并在有/无 node 两种环境下各跑一遍（无 node 时探针类用例 skip，静态契约照常生效）。
