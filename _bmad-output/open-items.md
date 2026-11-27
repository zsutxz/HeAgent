# Open Items — 活动台账（未闭合问题清单）

> 活动项正文真源（2026-11-15 由 `implementation-artifacts/open-items.md` 上移根目录；同一 ID 的正文只在此一处，不得两处并存）。
> 状态语义：`active`（有触发条件、未排期）／`scheduled`（已挂到 story 或 sprint）／`frozen`（挂起待裁定，**必须带裁定指针**——没有指针的「挂起」不是状态，是遗忘）。
> `retired`（显式退役，5 字段齐备）的规范与历史记录在 [`retrospective-all-cycles.md`](retrospective-all-cycles.md) §三。
> 当前状态总览与 epic 总目录见 [`epic-overview.md`](epic-overview.md)。

## 活动（未闭合）条目

当前活动项：**5 条**（`frozen` 1：A65；`active` 4：A55 / A67 / A77 / A78）。

| ID | 主题 | 状态 | 说明 |
| --- | --- | --- | --- |
| A55 | Epic 61 web_search 真实 Tavily 冒烟（61.3 验收残差） | `active` | **origin=新增（2026-11-16 Epic 61 收口，用户裁定跳过冒烟先闭合）**：61.1 引擎层（`66a5b9f`）/61.2 工具面（`1877250`）/61.3 文档收口已交付，三票 mark done；web_search 全链（config 解析→引擎调用→截断→围栏）未经真实密钥验证。闭合动作 = 用户提供 WEB_SEARCH_API_KEY 入 `.env` 后跑一次全链冒烟（参照 57-4 先例：临时 workspace，不触碰仓库记忆；key 不入 transcript/不入库/不入日志），通过后闭合 A55 并四处计数 7→6。**操作卡（2026-11-24 E78-S02）**：① 把 key 写进仓库根 `.env`（`WEB_SEARCH_API_KEY=…`，**不入库、不进 transcript、不进日志**）；② `python scripts/web_search_smoke.py --query "…"`（四段阈值可调 `--max-results`）；③ 通过判据 = 四段全 `[OK]` 且 exit 0（config 解析 / 引擎真调用 / 工具面截断 / 注入围栏）；④ 没 key 时先 `python scripts/web_search_smoke.py --self-check` 自检脚本本身（exit 0 即工具可用） |
| A65 | Pages 部署前置设置未验证（**用户裁定暂停**） | `frozen` | **origin=新增（2026-11-18 Epic 68 评审）**。`.github/workflows/docs.yml` 已就绪（触发分支含 `master` / `main` / `feat/module-integration`，`mkdocs.yml` 已配 `site_url`），但仓库 Settings → Pages 的 Source 必须选 “GitHub Actions” 才能部署，且从未跑过一次真实 `workflow_dispatch`。**裁定指针：2026-11-18 用户裁定「暂停」**（不推进 Pages 发布，站点构建门仍在 CI docs step 里照跑）。恢复条件 = 用户决定启用 Pages 时：改仓库设置 → 手动触发一次 → 确认 `page_url` 可访问（判据 = run 绿 + 200） |
| A67 | devcontainer 启动耗时为估算值 | `active` | **origin=新增（2026-11-19 Epic 65 retro #2 升台账）**。`README.md` / `.devcontainer/` 标「约 2–3 分钟」，但立项时所在开发容器无 docker daemon（`docker info` 不可用）⇒ 从未实测。触发条件 = 首次在有 daemon 的机器上 `devcontainer up`；闭合动作 = 回填实测值，偏差超 2 倍则改文案（判据 = 实测秒数写进 README 该行）。**2026-11-21 复测阻塞**：本开发容器 `docker info` = UNAVAILABLE 且无 `devcontainer` CLI ⇒ 仍无法实测；需在有 daemon 的宿主执行一次 `devcontainer up` 并回填。**操作卡（2026-11-24 E78-S03）**：① 在有 daemon 的机器上 `cd <repo> && time devcontainer up --workspace-folder .`；② 记 `real` 秒数并注明冷/热启动（首次含镜像构建）；③ 回填 `README.md`「约 2–3 分钟」那一行；④ 偏差 > 2 倍即改文案，判据 = 实测秒数写进该行 |
| A77 | `ws_project_adapter` 的 `except TimeoutError` 捕获面偏宽 | `active` | **origin=新增（2026-11-27 代码审查，落改提交 `73f9518d`）**。`_submit` / `ensure_available` 用 `except TimeoutError` 同时兜住 `wait_for` 的自身超时与**控制台内部**自抛的超时（内置 `TimeoutError` 就是 `asyncio.TimeoutError`）⇒ 后者会被重写成「did not complete within 30s; outcome unknown」这条误导文案，排障时会去查根本不存在的 30s 上界。触发条件 = 控制台或将来接入的 HTTP 客户端自抛超时；闭合动作 = 改 `asyncio.timeout()` 或给 `wait_for` 的异常做区分（只认本函数构造的那一档）；判据 = 新增一例「内层 `TimeoutError` 原样透传、不被改写成 `timeout` 码」 |
| A78 | cpolar 公网地址的回退分支无活性校验 | `active` | **origin=新增（2026-11-27 代码审查，落改提交 `73f9518d`）**。`scripts/cpolar_publish.py::public_address()` 的四级回读里 `address_from_admin_api` 只认 `tcp://` ⇒ 隧道改 `-Protocol http` 或管理面没起来时会退到 `cpolar-address.txt` / 预留地址，那可能是上一次运行留下的**已死地址**，`--apply` 会把它写进 App 的 `websocket_endpoint`。触发条件 = 隧道改协议、地址轮换、管理面不可用；闭合动作 = 回退命中时标注「未经活性校验」的来源并做一次 TCP 可达探测（或强制 `--address` 显式给）；判据 = 负向用例「死地址不被 `--apply` 写入」 |

### 速读（按行动姿态分组）

> 本节只列**活动**项，ID 集合须与上表逐字相等（已闭合 ID 一律迁 [`retrospective-all-cycles.md`](retrospective-all-cycles.md) §三，
> 不得留在本节——`tests/test_deferred_id_registry.py` 有可执行断言）。

- **等外部触发**：
  - A55 —— 用户提供 `WEB_SEARCH_API_KEY` 后跑一次真实全链冒烟
  - A67 —— 需在有 docker daemon 的宿主跑一次 `devcontainer up`，回填实测秒数
- **等用户裁定 / 恢复**：
  - A65 —— 用户裁定暂停 Pages 发布，恢复条件已写明
- **待排期（自审发现，无外部前置）**：
  - A77 —— `ws_project_adapter` 超时捕获面收窄：内层 `TimeoutError` 不得被改写成本实现方的 30s 文案
  - A78 —— cpolar 地址回退加活性校验：已死地址不得被 `--apply` 写进 App 的 `websocket_endpoint`

### 维护规则（活动项）

- 新增未闭合项**只写本节**：先登记 ID、状态（active / scheduled / frozen）、触发条件、裁定与验收证据，再开始实施；不要另建活动清单或复活历史档案活动区。
- `frozen` 必须带裁定指针（哪个 OQ / 哪份记录）。
- 闭合时把正文迁入 [`retrospective-all-cycles.md`](retrospective-all-cycles.md) §三（台账），或按归属 Epic 进 `epics/<周期>/deferred-work.md`，并从本表移除；**同一 ID 不得两处并存**。显式退役（裁定永不修）走 §三 的 `retired` 5 字段规范。
- `blocked` 需要产品或架构裁定，不能由实现者静默关闭。
