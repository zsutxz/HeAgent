# goal 进度：Goal-4

- 目标：WS 远程项目通道（多项目控制）
- Initiative：Goal-4（goal 目录本身即 initiative 根，Step 04 写定）
- 状态：in-progress
- 当前步骤：step-05-design-architecture

## 步骤状态

| 步骤 | 名称 | 状态 | 产物 |
|---|---|---|---|
| 01 | market-research | completed | `step-01-market-research/report.md` |
| 02 | brainstorm-options | completed | `step-02-brainstorm-options/report.md` |
| 03 | analyze-requirements | completed | `step-03-analyze-requirements/report.md` |
| 04 | define-product-scope | completed（approved 2026-11-23） | `prd-ws-remote-project-channel/prd-ws-remote-project-channel.md` + `tickets/`（3 个 epic） |
| 05 | design-architecture | in-progress | `architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md` |

## Epic 与 entry（Step 06 后维护，状态抄自 `tickets.py status`）

（空，Step 06 后填写）

## 决策日志（追加式，只增不改）

- 2026-11-23 `new-goal` 建骨架（goal=`ws-remote-project-channel`）
- 2026-11-23 Step 01 完成：子会话首轮超迭代失败（`Exceeded 15 iterations`），二次以「预算约束 + 聚焦两问」重跑通过；宿主核对 `http_console_protocol.py:389/455` 与 `ws_protocol.py` 的 `extra="forbid"` 均真实存在。**环境无 web 检索能力**（`web_search` 报缺 `WEB_SEARCH_API_KEY`，对应台账 A55）⇒ 全部外部论断记 gap，报告已写明。
- 2026-11-23 按默认值执行：Step 01 调研广度收敛为「项目选择层级 + 单连接请求级路由故障模式」两问（原四问降到两问），其余记为证据缺口。
- 2026-11-23 Step 02 轮 0 产出（Creative Partner，技法 = Working Backwards + Pre-mortem）：5 条候选方向（注入式只读端口 / 帧转译服务调用 / 契约快照先行 / 并发红测试倒驱动 / 只读投影最小暴露）＋ 1 条主追问（项目列表真源 = 已注册条目还是磁盘扫描）。**停在此处等用户回复**，不注册 cron。
- 2026-11-23 **用户裁决（原话）**「本机已注册的项目条目」⇒ 远程项目列表真源 = 本机注册表，不是磁盘扫描目录。
- 2026-11-23 Step 02 轮 1 + 收敛轮完成：宿主实测 `pub/projects.py` 后，方向 7 / 8 / 5 被实测证据消解（`available` 已在列表时算、启动工作区已是 `id="default"` 零号成员、`ProjectEntry` 已 frozen+有界）；落点定为「帧转译共用服务 + 入口注入只读端口 + 投影函数（剔 `path`/`last_opened_at`）」，验收条款 A–E 交 Step 03。
- 2026-11-23 **按默认值执行**（用户「有推荐的选推荐选项」口径）：轮 1 主追问（`project_id` 用既有注册表 id 还是新造代理键）采纳默认答案 = 复用既有 `ProjectEntry.id`、v1 不迁移、把 path-derived 稳定性登记为缺口。
- 2026-11-23 Step 03 完成：需求简报（10 条事实 / 5 条假设 / AC1–AC10）+ 7 条 story 粒度拆分（S1 帧契约 → S2 端口签名 → S3 转译共用服务 → S4 投影与注入 → S5 并发隔离 → S6 白名单与 WARNING → S7 契约交接）。宿主抽验通过：`RunWebSocketService` 是 Protocol（`ws_server.py:110 start_run(prompt)`）、`build_ws_servers(…, run_service=…)` 已是注入式装配点。5 条开放问题全部给默认处置（path-derived id 取 A 不迁移 / list 顺序以实现为准 / 列项目 fail-soft 而提交 fail-loud / `available` 提交前二次校验 / 缺省续最近会话）。

- 2026-11-23 Step 04 完成（待审批）：PRD 10 章落盘（R1–R14 / D1–D10 / NG1–NG13 / Q1–Q9）；信封段写进 `brief.md`（Requirements R1–R14 / Constraints 6 / Done when 8 / Boundaries 4 / Notes 7 条 Decision）；票树切 3 个 epic = E74 帧契约 / E75 项目链运行时 / E76 收口（`tickets.py status`：epics 74/75/76、problems 空、unpinned / undeclared / order_conflict 全空，counts total 0）。**停在 Step 04 审批门等用户确认**。
- 2026-11-23 Decision: epic 目录用 `epic-<编号>-<slug>` 而非纯 `<e编号>-…` —— 票树脚本 `EPIC_RE` 只认 `epic-*`、`epic_folders()` 只 glob `epic-*`，纯编号形态要改脚本且补丁会被角色包重装覆盖；人读编号仍写 `code` / `title` 前缀 / frontmatter 三处。

- 2026-11-23 **用户指令（原话）**「e:\AI\HeAgent\docs\ws-remote-project-channel这个目录改为Goal-4」⇒ goal 目录 `docs/ws-remote-project-channel/` 改名为 `docs/Goal-4/`；`docs/current` 置 `Goal-4`；`- Initiative:` 行改为 `Goal-4（goal 目录本身即 initiative 根）`；7 个文件内的 `docs/ws-remote-project-channel` 路径前缀与 4 份报告的「目标」标注同步更新。**保留不动**：`brief.md` 原始需求冻结段里的 ADR 文件名、`docs/decisions/` 的 ADR-005、PRD 产物目录名 `prd-ws-remote-project-channel/`、epic 目录 slug。

- 2026-11-23 **Step 04 审批门通过**：用户答复原文「yes」⇒ PRD + 三个 epic 确认，同时授权提交票树；已按中文 Conventional Commit 提交（`docs(goal-4): 立项 ADR-005 远程项目通道并落 PRD 与三个 epic`）。

## 交接块（下一轮入口）

- 下一条：Step 04 审批门（产出已齐，等用户 `approve` / `reject` / `amend`；批准后提交票树并进 Step 05）
- 票树实测：`status docs/Goal-4` → epics 74/75/76、counts total 0、problems 空、unpinned / undeclared / order_conflict 全空
- 必读：`prd-ws-remote-project-channel/prd-ws-remote-project-channel.md` · `brief.md` · `tickets/tickets.toml` · 三个 epic 文件 · `step-03-analyze-requirements/report.md`
- 未关闭的门：**Step 04 规划审批**（用户一「yes」同时授权提交票树）；Step 05 架构、Step 06 细化各还有一道门
- 本轮结论：切分轴 = 验收面（契约 → 运行时 → 收口），14 条 R 全覆盖无重叠；R7 仍是无 AC 的缺口，已指定由 E76 落成可跑断言；epic 目录形态取 `epic-<编号>-<slug>` 以兼容票树脚本。
