---
title: 'Story 70.4 前端消费覆盖守卫'
type: feature
ticket: 4
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
  - 'tests/test_http_web_ui.py'
  - 'src/heagent/network/http_server/app.py'
  - 'src/heagent/network/ws_host.py'
  - 'src/heagent/web/app.js'
---

## Intent

**Problem:** 端点与前端是两份各自演进的清单。Story 64.11 交付了 `/api/tasks` 之后，前端整整一个
epic 都没接入，而没有任何东西会因此变红 —— 这次能发现，纯靠人工对着路由表核对。同类风险是反向的：
前端留着一条指向已改路径的调用，只有点下去才 404。

**Approach:** 一条静态契约测试，双向断言：

1. 从 `src/heagent/network/http_server/app.py` 的模块级路径常量（`_HEALTH_PATH`、`_RUNS_PATH`、
   `_TASKS_PATH`、`_TASK_DETAIL_PATH`、`_PROJECT_*`、`_DIALOG_PICK_PATH` 等）收集 HTTP 路由。
2. 从 `src/heagent/web/*.js` 里提取 `/api/...` 字面量（含模板串里的固定前缀段，如
   `/api/projects/` + `encodeURIComponent(...)`）。
3. **正向**：每条 HTTP 路由要么在「已消费」集合里，要么在显式白名单里；白名单条目**必须带理由
   字符串**（例如 `POST /api/runs`：非项目作用域的裸提交口，网页端走 `POST /api/projects/{id}/runs`，
   刻意不用），没有理由即失败。
4. **反向**：前端出现的每条 `/api/...` 前缀都必须能匹配一条真实路由，否则失败并点名。

实现形态：路径比较用「规范化模板」而不是字符串相等 —— 前端拼的是 `/api/projects/{id}` 的实际值，
测试要按段前缀匹配到路由模板，避免把 `encodeURIComponent` 拼出来的动态段误判为不存在。

## 判据

- 删掉 `app.js` 里对 `GET /api/health` 的调用 → 测试红，消息点名 `/api/health`。
- 在 `app.py` 新增一条假路由（不接前端、不入白名单）→ 测试红，消息提示「接入网页端或加白名单」。
- 白名单每条都写理由；测试里断言理由非空。
- 反向：把 `app.js` 里某条路径改成 `/api/typo` → 测试红并点名 `/api/typo`。
- 现有 `tests/test_http_web_ui.py` 的静态契约断言不被破坏；全量测试与 `tests/test_architecture_contracts.py` 全绿。

## 落点

- `tests/test_web_endpoint_coverage.py`（**独立文件**，不塞进 `test_http_web_ui.py`：那里是页面静态契约，
  这里是路由 ↔ 前端的覆盖关系，混在一起会让两边都难读；也不放 `test_architecture_contracts.py`，
  那条文件守的是包间依赖）
- 断言消息必须**点名具体端点**（便于无人值守时直接看懂）
- 提取器按 `web/*.js` 通配，而不是只读 `app.js`

## 风险

- 提取器对模板串敏感：写死「只认单引号字符串」会漏掉 `${...}` 拼接。实现时按「去掉插值后保留
  固定前缀」处理，并补一条针对动态段的用例，防止守卫本身假绿。
- 白名单是逃生门：要留，但必须带理由，且不允许多条目共用一句笼统理由（测试里可断言理由长度下限）。

## 评审（2026-11-19）

| 判据 | 证据 | 结论 |
| --- | --- | --- |
| 正向：新路由未接前端且不在白名单 ⇒ 红并点名 | `test_guard_detects_a_new_unconsumed_route`（monkeypatch 注入 `/api/guard-probe`） | 满足 |
| 反向：前端路径拼错 ⇒ 红并点名 | `test_guard_detects_a_typo`（注入 `/api/typo`） | 满足 |
| 白名单每条带理由且指向真实路由 | `test_whitelist_entries_still_exist_and_have_reasons`（理由长度下限 12） | 满足 |
| 守卫本身看得见东西 | `test_frontend_paths_are_discovered`（≥10 条且含 `api-console.js`）、`test_backend_route_parser_sees_the_task_endpoints` | 满足 |
| 真实文件的变异可检 | 两条 monkeypatch 变异分别作用在路由集合与前端路径集合上 | 满足 |

**已知边界（未立台账）**：`_matches` 允许「前端前缀路径匹配更长的路由模板」（`/api/tasks` 落在
`/api/tasks/{task_id}` 上）。反向断言因此抓不到「后端删掉**集合路由**、详情路由仍在」这一种漂移。
取舍写在模块 docstring 里：前端拼的是动态 id，必须按段前缀对齐；替代方案（要求方法 + 精确模板）
需要从 `fetch(url, {method})` 静态还原方法，成本高于收益。风险面是「某端点被删」而非「新增未接」，
后者正是本守卫要防的那类静默缺口。
