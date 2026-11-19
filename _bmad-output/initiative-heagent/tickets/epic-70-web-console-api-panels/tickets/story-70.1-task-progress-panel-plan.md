---
title: 'Story 70.1 网页端任务进度面板'
type: feature
ticket: 1
created: '2026-11-19'
status: built
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
