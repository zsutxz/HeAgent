---
title: 'Story 70.3 同源 API 探索器'
type: feature
ticket: 3
created: '2026-11-19'
status: done
baseline_revision: '329311d'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: []
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/web/index.html'
  - 'src/heagent/web/app.js'
  - 'src/heagent/network/http_server/app.py'
  - 'src/heagent/network/http_server/middleware.py'
  - 'src/heagent/network/origin.py'
  - 'tests/test_http_web_ui.py'
---

## Intent

**Problem:** 网页端只能点它自带的按钮；要看任意端点的原始响应，必须开 DevTools 手敲 `fetch`。
上一轮实测已确认独立 HTML 页面走不通（`file://` 的 `Origin: null` 被 `_OriginGuardMiddleware`
判 403，且服务端零 CORS 头、CSP 为 `connect-src 'self'`）——**同源是唯一可行路径**，所以探索器
必须是页面内的一部分，而不是外挂文件。

**Approach:** 页面内开发者面板，纯前端实现：

1. 表单：方法（GET / POST / PATCH / PUT / DELETE）+ 路径（必须以 `/` 开头）+ 可选 JSON body。
2. 预置清单：把 `app.py` 里已存在的路由列成可点条目（含 `{project_id}` / `{session_id}` 占位，
   用当前选中的项目/会话自动填充），清单与后端路由表的一致性由 70.4 的守卫测试保证。
3. 执行：同源 `fetch`，记录 `performance.now()` 耗时，展示状态码 + 耗时 + 响应体（超长截断并标明）。
4. 渲染：`textContent`；不使用 `innerHTML`（现有断言会红）。
5. 安全闸门（前端礼貌，不是安全边界）：写方法先弹二次确认；`DELETE` 提示 `?confirm=true`
   这类服务端闸门的存在；错误信封里的 `code` 原样展示（便于查 `docs/errors.md`）。

## 判据

- probe 场景：GET 成功 → 面板出现状态码、耗时（数字）、格式化 JSON。
- probe 场景：400 错误信封 → 展示 `error.code` 与 `error.message`。
- probe 场景：写方法未点确认 → **不发请求**（断言 fetch 调用计数为 0）。
- 预置清单的每条路径都能在 `app.py` 路由常量里命中（该断言与 70.4 共用实现）。
- 无第三方资源、无内联脚本/样式、CSP 未放宽（`middleware.py` 的 `_SECURITY_HEADERS` 零 diff）。

## 落点

- `src/heagent/web/index.html`（面板结构，`hidden` 默认收起；`#api` 直达）
- `src/heagent/web/app.js`（提交/渲染逻辑；如体量过大再拆 `api-explorer.js` 并同步 `_WEB_ASSETS`）
- `src/heagent/web/styles.css`
- `tests/test_http_web_ui.py` / `tests/fixtures/js/app_probe.js`

## 风险

- **这是本 epic 唯一的 risk=medium 条目**：它给页面加了一个可以发任意同源请求的输入面。
  缓解：默认收起、写方法二次确认、路径必须以 `/` 开头、不代理、不带凭据、不做跨源；
  并且它不比 DevTools 更强大 —— 能打开这个页面的人本来就能开 Console。
- 与 CSP 的关系：`connect-src 'self'` 允许同源 fetch，但**不允许**任何外部主机；不要为了
  「顺手测外部 URL」去放宽 CSP。
- 面板不得进入默认首屏动线（避免被当成普通功能误触）。

## 评审（2026-11-19）

| 判据 | 证据 | 结论 |
| --- | --- | --- |
| 静态：资源白名单 / 元素绑定 / `confirm` 在请求之前 / 预置与路由双向 | `tests/test_web_api_console.py` | 满足 |
| 行为：GET 成功显示状态码 + 耗时 + 格式化 JSON | `panels_probe.js` case `api-get` → `TestApiConsoleProbe`（node）：`HTTP 200 (12 ms)` + 两空格缩进 | 满足（本轮补探针） |
| 行为：400 错误信封显示 `code` 与 `message` | probe → 状态行 `bad_request: path is required` | 满足 |
| 行为：写方法未确认不发请求 | probe → 取消：`prompts=1` / `calls=0`；确认后 `posted=1` | 满足 |
| 本地拦截：路径不以 `/` 开头 / 请求体非 JSON / 占位符未替换 | probe case `api-guard` → 三种情形 `calls=0` | 满足（本轮补） |
| 预置清单每条都能在后端路由表命中 | `test_presets_cover_exactly_the_backend_routes`（21 条逐对比对） | 满足；提交信息写「20 条」是笔误，代码与测试都是 21 |

**评审记录**：探针里 `elapsed` 由 `performance.now()` 替身固定步进 12ms 得出，断言只钉格式与
「有数字」，不钉真实耗时。
