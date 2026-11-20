---
title: 'Story 71.6 网页端状态面板与徽标'
type: feature
ticket: 6
created: '2026-11-19'
status: done
baseline_revision: 'c0acda0c'
route: full
route_source: auto
risk: low
review: thorough
review_source: auto
lenses_ran: [edge-case-hunter, verification-gap]
review_loop_iteration: 0
followup_review_recommended: false
context:
  - 'src/heagent/web/index.html'
  - 'src/heagent/web/app.js'
  - 'src/heagent/web/tasks.js'
  - 'src/heagent/network/http_protocol.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** `GET /api/status`（71.1–71.5）已经吐出五组事实，但网页端一个字段都没消费——要看见它们只能开 API 探索器手工发请求。顶栏仍然只回答「活着 + 哪个版本」。

**Approach:** 新增静态资源 `web/status-panel.js`：顶栏徽标 `#server-status` 显示「模式 · uptime · 在途 run · WS 连接数」，侧栏新增默认收起的「服务器状态」`<details>` 面板，五组事实装进一条横向 tab 条（`role="tablist"`，一次只渲染选中的一组，切页签用最近快照重渲染、不额外取数），组内按 `label: value` 行表渲染；取数**只在面板展开时**轮询（5s），收起即停、标签页隐藏即停、失败保留上次渲染值并标离线。

## Boundaries & Constraints

**Always:**
- 纯静态资源：零第三方依赖、零内联脚本、零 `innerHTML`/`insertAdjacentHTML`/`document.write`，全部 `textContent` + `createElement`。
- 取数只走同源 `GET /api/status`（经 `window.HePanels.request`，HTTP 错误也是结果而非异常）。
- 轮询**不进** app.js 的 5 秒 health 循环：`app.js` 里不得出现 `/api/status`。
- 失败语义 = 保留上次值 + 标离线（沿用 70.2 的徽标纪律），绝不清空已渲染内容。
- `active_runs`（服务级）与 `max_inflight_runs`（每项目级）**不得**按比率渲染（71.1 评审裁定：作用域不同，`2 / 1` 会被读成超卖）。徽标只报 `run N`，上限单独一行且标注「单项目」。
- 新增资源必须进 `assets.py` 的 `_WEB_ASSETS` 白名单，并在 `index.html` 里真实引用（双向守卫）。
- `null` 资源字段显示为「不可用」，不填 0；`resource_source` 单独一行说明通路。

**Never:**
- 不改 `/api/status` / `/api/health` 契约，不改后端任何端点行为。
- 不做历史趋势、不做告警推送、不引图表库（epic Boundaries 已定）。
- 不把状态请求塞进 `checkHealth()`、不在面板收起时继续打服务端。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| BOOT | 页面加载、面板收起 | 徽标被一次取数填充并可见；`#server-groups` 不渲染（懒加载） | 失败：徽标 `data-state=offline` |
| OPEN | 用户展开 `<details>` | 立即取一次并渲染五组；开始 5s 轮询 | 无 |
| CLOSE | 用户收起 | 停表（`stopPolling`），不再发请求 | 无 |
| HIDDEN | 标签页不可见 | 停表；恢复可见且面板展开时立刻补一次 | 无 |
| STALE | 取数 500 / 网络失败 | 上次值全部保留；状态行给 `describeFailure` 文案；徽标 `offline` | 不抛、不清空 |
| NULL_RESOURCE | `rss_bytes=null`、`resource_source="unavailable"` | 资源行显示「不可用」，通路行显示 `unavailable` | 不填 0 |
| EXTERNAL | 任一 listener `mode=external` | 徽标模式段显示「对外」 | 无 |
| NO_LISTENER | `listeners=[]` | 徽标模式段显示「未暴露」 | 无 |

</intent-contract>

## Code Map

- `src/heagent/web/index.html` -- 顶栏 `#service-meta` 之后加 `#server-status` 徽标；侧栏任务面板之后加状态面板；`<script src="/status-panel.js">` 排在 `panels.js` 之后、`app.js` 之前。
- `src/heagent/web/status-panel.js` -- **新增**：取数、格式化、五组渲染、徽标、轮询启停。
- `src/heagent/web/styles.css` -- 新增 `.status-rows`（`dt`/`dd` 两列网格）与组标题样式。
- `src/heagent/network/http_server/assets.py` -- `_WEB_ASSETS` 加 `"status-panel.js"`。
- `src/heagent/network/http_protocol.py` -- 只读参考：`StatusResponse` 及嵌套模型字段即面板字段全集。
- `tests/test_http_web_ui.py` -- `test_page_is_self_contained` 的 refs 字面量列表必须加 `/status-panel.js`。
- `tests/test_web_endpoint_coverage.py` -- 不改：`status-panel.js` 里的 `/api/status` 会被自动发现，双向断言更实。
- `tests/test_web_server_status_panel.py` -- **新增**静态契约 + 字段覆盖守卫。
- `docs/frame.md` -- 静态资源面那一行补 `status-panel.js`。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/web/status-panel.js` -- 新增脚本：`POLL_MS=5000`、`loadStatus()`、`startPolling()`/`stopPolling()`、`renderBadge()`、`renderGroups()`、`duration()`/`bytes()`/`num()` 格式化；`<details>` toggle 与 `visibilitychange` 驱动启停 -- 面板不存在时静默返回，不抛。
- [ ] `src/heagent/web/index.html` -- 徽标 `#server-status`（`hidden` 起始）、侧栏 `<details id="server-details">` + `#server-groups` + `#server-panel-status`、脚本引用 -- 与既有徽标同款 `badge`/`data-state` 形态。
- [ ] `src/heagent/web/styles.css` -- `.status-rows` 两列网格（`dt` 灰、`dd` 右对齐可断行）-- 窄侧栏不溢出。
- [ ] `src/heagent/network/http_server/assets.py` -- 白名单加一条 -- 否则 `read_web_asset` 抛 `KeyError`、页面 404。
- [ ] `tests/test_http_web_ui.py` -- refs 期望列表加 `/status-panel.js` -- 既有字面量断言会红。
- [ ] `tests/test_web_server_status_panel.py` -- 新增：资源白名单/页面引用、唯一端点字面量、零注入 sink、零第三方资源、无硬编码版本、轮询启停与可见性分支存在、失败文案存在、徽标不按比率渲染、`app.js` 不含 `/api/status`、**字段覆盖守卫**（`StatusResponse` 及嵌套模型字段名必须全部出现在脚本里，服务身份三字段豁免并注明理由）-- 后端加字段而面板不跟进即红。
- [ ] `docs/frame.md` -- 1337 行静态资源行补 `status-panel.js` -- 文档不得落后于资源白名单。

**Acceptance Criteria:**
- Given 控制台页面加载, when 面板保持收起, then 徽标有内容且 `#server-groups` 为空（懒加载）。
- Given 面板展开, when 5s 到点, then 再次 `GET /api/status`；收起或标签页隐藏后不再发。
- Given `/api/status` 返回 500, then 已渲染行不变、状态行显示错误码文案、徽标 `data-state=offline`。
- Given `StatusResponse` 新增一个字段, then 字段覆盖守卫红（除非同步面板或写进豁免）。
- Given `node` 缺失, then 静态契约与字段覆盖仍全绿（行为由 node 探针覆盖，本机 skip）。

## Implementation Notes

- 落地形态与计划一致：`web/status-panel.js`（新）→ `index.html` 徽标 + `<details>` 面板 + 脚本引用 → `styles.css` 行表样式 → `assets.py` 白名单 → 双份守卫测试与文档。
- **偏离 1（徽标格式）**：epic 信封写的徽标形态是 `run 0/1`，71.1 的评审记录已明确「`active_runs` 服务级 / `max_inflight_runs` 每项目级不得按比率渲染」。徽标因此只报 `run N`，上限在面板「单项目并发上限」单独一行；`tests/test_web_server_status_panel.py::TestBadge::test_badge_does_not_render_a_ratio` 钉住 `renderBadge` 里不出现 `max_inflight_runs` 与除号。
- **偏离 2（取数桥）**：脚本不直接 `fetch`，走 `window.HePanels.request`（同源 + HTTP 错误即结果）。因此 `tests/test_web_endpoint_coverage.py` 看到的 `/api/status` 字面量仍在脚本里，双向断言不需要改动。
- **轮询形态**：`setTimeout` 串排程（不用 `setInterval`），排程条件 = 面板展开 且 标签页可见；页面加载时只取一次填徽标（面板保持收起时不渲染明细），展开立刻补一次、收起即停。
- **新增守卫**：`tests/test_web_server_status_panel.py` 的 `TestFieldCoverage` 把 `StatusResponse` 与 7 个嵌套模型的字段名逐一对读脚本源码（服务身份三字段豁免，理由写在文件头）——后端加字段而面板不跟进即红；另有一条 `_ProbeModel` 变异用例证明该守卫不空转。
- **无 node**：本机 `shutil.which("node")` 为 `None`，`tests/test_http_web_ui.py` 的 node 探针仍 skip；本站补了「括号配平」自查代替 `node --check`。
- **实测**：`TestClient`（`base_url=http://127.0.0.1:9101`）下 `/` 200（含 `#server-status` / `#server-details` / `status-panel.js` 引用）、`/status-panel.js` 200 `text/javascript`、`/api/status` 200 且 24 个键与 `StatusResponse` 一致。

## Verification

**Commands:**
- `python -m pytest tests/test_web_server_status_panel.py tests/test_http_web_ui.py tests/test_web_endpoint_coverage.py tests/test_web_api_console.py tests/test_web_tasks_panel.py tests/test_http_status_api.py -q` -- 276 passed / 34 skipped（node 探针）
- `python -m pytest -q`（全量）-- 5425 passed / 51 skipped / 30 deselected / 1 xfailed
- `python -m ruff check src tests` / `ruff format --check` / `mypy src` -- 全绿（475 files formatted / 233 source files）
- `python -m mkdocs build --strict` -- 0 warning；`python scripts/contract_snapshot.py --check` -- 四份快照全 `[OK]`

## Code Review

### 2026-11-19（lenses: edge-case-hunter + verification-gap）

**Code review complete.** 1 `decision-needed`, 3 `patch`（已修）, 1 `defer`, 5 rejected。

- [ ] [Review][Decision] `status-panel.js` 没有任何**执行级**测试 — 本计划的 AC 与实现说明都称「真实浏览器里的轮询节奏由 node 探针覆盖」，但 `tests/fixtures/js/app_probe.js` 只加载 `app.js`，`tests/test_http_web_ui.py::_run_probe` 只写 `app.js` + `index.html`，本文件从未被执行（本机与 CI 均无 node）。静态契约只能证明「源码里有这些 token」：删掉 `void loadStatus()`（徽标永不出现）、去掉 `shouldPoll` 的 `open` 条件（收起后继续轮询）、把失败分支写反（500 当快照渲染）都能全绿。Options: (a) 新增 `status_panel_probe.js`（照 app_probe 形态：最小 DOM + `HePanels` 桩，node 缺失时 skip），(b) 把「无 node ⇒ 前端行为零回归」升为 epic 级残差并在文档标注，(c) 两项都做。Recommended: (c) — 探针先落地（CI 镜像自带 node），本机 skip 由残差如实登记。
- [x] [Review][Patch] 取数永不 settle 时面板永久卡死 — 连接半开时 `fetch` 不返回，`loading` 恒 true，后续每次取数提前返回。已加 `REQUEST_TIMEOUT_MS = 4000` 的 `Promise.race`（超时按失败处理，轮询照继续）。
- [x] [Review][Patch] 「只调 `GET /api/status`」的方法面未断言 — 已补 `panels.request("GET"` 静态断言（改成 POST 会让每次轮询 405、面板永久离线）。
- [x] [Review][Patch] 依赖态未标注统计范围 — 已加「统计范围: 本进程工作区」行（与 71.3 的面板文案要求对齐）。
- [x] [Review][Defer] 字段覆盖守卫是全文子串匹配 — 实测 29 行里 12 行删掉后守卫仍绿（`active_runs` / `uptime` / `failed` 等被徽标或 `dataset` 里的同名字符串遮蔽）— deferred: A74

Rejected:
- false：字段缺失时面板把「未知」渲染成事实值（`WS 0` / `只读` / `未暴露`）— `StatusResponse` 是封闭模型，载荷恒带全字段；该状态只能由非本仓服务端产生。
- rejected(low)：渲染函数抛错会让轮询停摆 — 只在渲染代码自身有 bug 时发生，归入上面 decision 项同一风险面。
- rejected(low)：轮询启停 / 切页签不重取 / 失败保留三组语义无执行验证 — 与 decision 项同一根因，不重复立项。
- rejected(low)：`<details>` 收起时仍渲染明细 — `loadStatus` 已用 `el.details.open` 守卫。
- rejected(low)：`app.js` 是否含 `/api/status` — 已有静态断言钉住（`TestPollingIsNotInAppJs`）。
