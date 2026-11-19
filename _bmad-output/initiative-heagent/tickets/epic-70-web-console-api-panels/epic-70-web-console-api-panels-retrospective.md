---
epic: epic-70-web-console-api-panels
date: 2026-11-19
verdict: accepted
criteria: declared
headless: false
---

# Epic 70 Retrospective

> 路径约定：`tickets/story-70.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-70-web-console-api-panels/`；
> 其余路径相对仓库根。门禁实测为 2026-11-19 补做本 retro 时现场复跑
> （容器内 `.heagent/tmp/py311-venv-linux/bin/python`，`PATH` 前置 `node v20.18.1`）。

## Epic summary

**Epic**：epic-70-web-console-api-panels（R10；4 story，全部新建，无 v6 迁移键）

**票态**：4/4 `done`，无 `dropped`。

**立项依据**（2026-11-19 实测）：HTTP listener 已有 18 条路由，网页端对其中 `/api/tasks`、
`/api/tasks/{task_id}`、`/api/session` **零消费**，且没有任何「对任意端点发起请求」的入口；
`file://` 独立页面因 `Origin: null` 被同源防线 403、服务端零 CORS，不可行。

| Entry | 交付 | 提交 |
|---|---|---|
| 70.1 网页端任务进度面板 | `web/tasks.js`（221 行）：列表按后端顺序渲染 task_id / kind / status / percent / 时间，选中看详情；有 pending·running 才轮询、全终态即停；空态与失败各有文案；只用 `textContent` | `dadafc0e` |
| 70.2 服务状态条与进程会话快照 | `web/app.js`(+93) / `index.html`(+48) / `styles.css`(+69)：`/api/health` 的 service·version·schema_version + `/api/session` 快照；徽标首段写明「本进程」；断连保留上次值并标离线 | `dadafc0e` |
| 70.3 同源 API 探索器 | `web/api-console.js`（240 行）：方法 + 路径 + 可选 body → 同源 `fetch` → 状态码·耗时·格式化 JSON；21 条预置端点每条都能在后端路由表命中；写方法二次确认 | `dadafc0e` |
| 70.4 前端消费覆盖守卫 | `tests/test_web_endpoint_coverage.py`（179 行）：静态提取前端 `/api/...` 字面量 ↔ 后端路由常量双向断言；白名单带理由字符串；两条 monkeypatch 变异自证 | `dadafc0e` |

**收口轮（`bcf0e095`）**：装上 node 20.18.1 后补三面板行为探针——`tests/fixtures/js/panels_probe.js`（509 行）
与 `app_probe.js` case `Y`，共用新增的 `tests/helpers_js_probe.py`（63 行）；同时修掉一处**只在有 node
环境下可见**的回归（见下）。

## 收口轮修掉的问题

| 问题 | 根因 | 修法 / 判据 |
|---|---|---|
| 终态刷新多拉一次 `GET /api/session`，使 `tests/test_http_web_ui.py` case M 的「被拒提交总调用数 == 4」变成 8 | 该断言数的是**全部** fetch，而 70.2 新增了终态刷新路径；开发容器无 node 时此用例 skip ⇒ 长期不可见 | 断言收窄到提交口 `POST /api/projects/default/runs`，保留「不重试、不静默」原意 |
| 徽标只靠 hover `title` 说明「当前进程」语义，可见文本仍是「会话 s1」 | 70.2 首版文案欠明确 | `renderSessionSnapshot` 首段加「本进程」，探针断言逐字文本 |
| 面板「取数中」在请求不 settle 时永久挂起 | `fetch` 无超时 | 探针断言 `state=failed` 与保留上次渲染（行为面）；后端零改动 |
| 70.1 plan 原写详情 404 错误码 `unknown_task` | 端点复用通用错误码，plan 属推测 | 以实测为准：`not_found: no such task` |

## 门禁实测（补做 retro 时复跑）

```text
pytest -q（PATH 含 node v20.18.1）   → 5518 passed / 17 skipped / 30 deselected / 1 xfailed（0 failed，276s）
ruff check src tests scripts examples → All checks passed
ruff format --check                   → 514 files already formatted
mypy src                              → no issues in 233 source files
bandit -r src/ -ll                    → High/Medium/Low 全 0
mkdocs build --strict                 → 0 warning（4.34s）
```

## 教训

- **「静态契约绿」不等于行为正确**。70.1–70.3 首版的用例全是源码子串与结构断言，`tasks.js` /
  `api-console.js` 从未被执行过；本仓 `app_probe.js` 原本只 `load()` `app.js`，不覆盖新面板 ⇒
  引用「已有 node 探针」之前必须先确认它加载的是哪个文件，否则得到的是虚假的覆盖感。
- **只在单一环境可见的断言最危险**。case M 的「总数 == 4」在无 node 环境永久 skip、在有 node 环境必红；
  跨 story 新增请求路径时，`fetch` 总计数类断言应从第一天就锚定到具体端点，而不是数总量。
- **文档与提交信息里的数字要和常量同源**。70.3 提交信息写「20 条预置端点」，代码与测试都是 21 条；
  这类笔误不影响门禁，但会让 `git log` 成为第二个事实源。
- **plan 里的错误码、文案、字段名都是待验证的假设**。两处（404 码、徽标文案）都是实测推翻了 plan 原文，
  正确处置是「以实测为准 + 在 plan 的评审段留证」，而不是改测试去迁就 plan。

## 残差与待裁定

- **无新增台账项**。70.4 的一条已知边界（`_coverage._matches` 允许前端前缀路径匹配更长的路由模板 ⇒
  抓不到「后端删掉集合路由、详情路由仍在」）按 plan 记录**有意不立台账**：取舍已写进模块 docstring
  ——前端拼的是动态 id，必须按段前缀对齐；替代方案需从 `fetch(url, {method})` 静态还原方法，
  成本高于收益；风险面是「端点被删」而非「新增未接」，后者才是本守卫要防的静默缺口。
- **前端行为回归依赖 node**：无 node 环境下探针类用例 skip，CI 上字段与结构守卫照常生效。
  是否值得为无 node 环境补第二通路，见 Open questions。
- 三处后端装配面（`network/http_server/assets.py` 静态资源白名单 +3）属必需改动，
  「后端零 diff」按「路由与端点零 diff」口径成立。

## Open questions

1. `app_probe.js` 的用例键是单大写字母（A–Y 已占），新增面板探针挤在同一文件里撞键会**静默覆盖**
   旧用例（表现为别的用例 `KeyError`）。是否把 panels 探针整体留在 `panels_probe.js` 单入口，
   让 `app_probe.js` 只覆盖 `app.js`？
2. 无 node 环境是否提供第二通路（纯函数导出 + Python 侧结构断言），还是维持「CI 必须有 node」作为口径？
3. 三面板与状态面板都各自轮询，页面全展开时的请求量是否需要合并成一次「页面级快照」拉取？
