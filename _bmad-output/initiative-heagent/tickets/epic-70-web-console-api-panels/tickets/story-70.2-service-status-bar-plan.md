---
title: 'Story 70.2 服务状态条与进程会话快照'
type: feature
ticket: 2
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
  - 'src/heagent/web/app.js'
  - 'src/heagent/web/index.html'
  - 'src/heagent/network/http_protocol.py'
  - 'src/heagent/network/http_server/service.py'
  - 'src/heagent/network/http_server/endpoints_run.py'
  - 'tests/test_http_web_ui.py'
---

## Intent

**Problem:** 网页端已调 `GET /api/health`，但只判 `status === "ok"`（`app.js::checkHealth`），
把 `service` / `version` / `schema_version` 三个字段扔掉了 —— 用户在界面里看不到自己连的是哪个版本；
`GET /api/session`（`service.session_snapshot()`：会话 id、当前或最近运行 id/状态、已完成消息）
更是零消费。

**Approach:** 把状态从「二值在线」升级为「在线 + 可核对的身份信息」，两段各自可测：

1. `checkHealth` 保留 `status` 判定，同时把 `service` / `version` / `schema_version` 渲染进状态条。
   **版本号只来自响应体**：前端不得写死任何版本串（判据即「改后端版本 → 前端展示跟着变」）。
2. 新增一次 `GET /api/session` 拉取（按需，例如切换项目/提交运行后各取一次，不做常驻轮询），
   展示 `session_id` / `run_id` / `status` / 消息条数；`run_id` 为 `null` 时显示「暂无运行」。
3. 断连语义：`checkHealth` 失败时**保留上一次的值**并标注离线（不把界面清成空白），恢复后自动回 `ready`。

## 判据

- 断言前端源码里没有硬编码版本串（避免 `0.10.0` 这类常量进 `app.js`）。
- probe 场景：health 返回 `version: "9.9.9"` → 状态条显示 `9.9.9`；再返回另一个值 → 跟着变。
- probe 场景：`/api/session` 返回 `run_id: null` → 显示占位；有 `run_id` + `status` → 两者都可见。
- probe 场景：health 先 200 再连接失败 → 状态条变离线但保留旧版本串；再 200 → 回 ready。
- 静态契约：无第三方资源、无 `innerHTML`、无内联 style（沿用现有断言）。

## 落点

- `src/heagent/web/app.js`（`checkHealth` 扩展 + 新的 session 拉取与渲染）
- `src/heagent/web/index.html`（状态条容器与占位文案）
- `tests/test_http_web_ui.py` / `tests/fixtures/js/app_probe.js`

## 风险

- `/api/session` 是**进程级**单用户快照，与「项目内会话」不是一回事（控制台的多数操作走
  `/api/projects/{id}/sessions`）。文案必须写明「当前进程」，否则会被读成「项目会话」。
- 不要把 `/api/session` 接进现有 SSE 循环（它是快照，不是事件流）。
