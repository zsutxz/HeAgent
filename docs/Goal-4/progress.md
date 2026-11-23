# goal 进度：Goal-4

- 目标：WS 远程项目通道（多项目控制）
- Initiative：Goal-4（goal 目录本身即 initiative 根，Step 04 写定）
- 状态：in-progress
- 当前步骤：step-07-implement-story（E74 五条全 built ⇒ 下一步 = E74 收口三审，须在新会话开跑）

## 步骤状态

| 步骤 | 名称 | 状态 | 产物 |
|---|---|---|---|
| 01 | market-research | completed | `step-01-market-research/report.md` |
| 02 | brainstorm-options | completed | `step-02-brainstorm-options/report.md` |
| 03 | analyze-requirements | completed | `step-03-analyze-requirements/report.md` |
| 04 | define-product-scope | completed（approved 2026-11-23） | `prd-ws-remote-project-channel/prd-ws-remote-project-channel.md` + `tickets/`（3 个 epic） |
| 05 | design-architecture | completed | `architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md`（8 条 AD / 10 条不变量） |
| 06 | refine-stories | completed（approved 2026-11-23） | `tickets/<epic>/tickets/tickets.toml`（17 条 entry）+ `step-06-refine-stories/report.md` |
| 07 | implement-story | in-progress（E74 全 built，待收口三审） | 各 entry 的 plan（`tickets/<epic>/tickets/story-*-plan.md`） |

## Epic 与 entry（Step 06 后维护，状态抄自 `tickets.py status`）

- E74 `epic-74-ws-frame-contract`：5 entry，全部 built（74.1–74.5）——待三审收口
- E75 `epic-75-project-channel-runtime`：6 entry，0 built
- E76 `epic-76-remote-surface-closeout`：6 entry，0 built
- 合计 `counts {total: 17, review: 5, planned: 12}`；`unpinned_after` / `undeclared_after` / `order_conflict` 全空

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

- 2026-11-23 Step 05 完成：spine 8 条 AD / 10 条不变量落盘，三个 epic 的 `sources:` 已采纳。子会话三处实测偏差被采纳：① engine 里没有并发名额（名额在 run 服务 + console）；② `RunWebSocketService` 不扩展、新增并列 `ProjectChannelService`；③ `start_project_run` 返回带 `session_id` ⇒ 适配器必须收窄。
- 2026-11-23 Step 06 完成（待审批）：三个 epic 各写 7 条 Requirements + 置 `refined: true`；17 条 entry（74×5 / 75×6 / 76×6），`tickets.py status` = `{total:17, planned:17}`、problems 空、三个依赖检查全空。12 条「需裁决」全部按默认处置关闭（详见 `step-06-refine-stories/report.md` 的「宿主裁决」表）。
- 2026-11-23 **路径修正**：契约快照实际目录是 `tests/fixtures/contract_baselines/`（非 `tests/contract_baselines/`）；spine / brief / PRD / 报告中的写法已全量替换修正。
- 2026-11-23 Decision: `ProjectChannelService` Protocol 与 `SubmittedRun` 的定义归 74.1（帧与端口形状），75.2 只做 `_submit_run` 分支与判据 —— 否则 74.1 的类型注解会对 75.2 造成前向依赖。

- 2026-11-23 **Step 06 审批门通过**：用户答复原文「yes」⇒ Requirements + 17 条 entry 确认，已提交（`7ba444cc`）。
- 2026-11-23 **74.1 built**：实现子会话在 26 次迭代处超限退出（留下 `ws_protocol.py` / `ws_server.py` 改动），宿主接手补 `tests/network/test_ws_command_fields.py`（5 例）与 plan、逐条实测后 `mark 74.1 built`。验证：`pytest tests/network tests/test_architecture_contracts.py -q` = 658 passed；ruff / format / mypy 全绿。已提交 `d6e705de`。
- 2026-11-23 Decision: 74.1 的 `ProjectChannelService` 只声明 `start_project_run` / `ensure_available` 两方法（`list_projects` 留 75.3），否则 74.1 的类型注解会对 75.3 的 `WsProjectsFrame` 造成前向依赖。

- 2026-11-23 **74.2 built**：实现子会话在 26 次迭代处超限退出（未回报），留下 `ws_server.py` 的完整改动与 `tests/network/test_ws_project_submit.py` 全文；宿主接手按 `## Verification` 逐条实测、核 `verify` 四判据与 `wc -l` 上限后 `mark 74.2 built`，已提交 `eeb7fee9`。验证：`pytest tests/network tests/test_architecture_contracts.py -q` = 668 passed；`pytest tests/network/test_ws_project_submit.py tests/network/test_ws_command_fields.py -q` = 10 passed；ruff / format / mypy 全绿。
- 2026-11-23 Decision: 「未装配却带 `project_id`」的护栏从 `_handle_submit_commands` 搬进 `_start_project_run` 顶部（code / message 逐字不变），循环只做转发——否则项目提交搬进 `_submit_run` 后循环里那道判定成为不可达的第二份真源。74.1 的既有 5 例是这个搬动的判据（仍全绿）。
- 2026-11-23 **余量告警（留给 E75）**：`network/ws_server.py` 现 988 行，距单文件 1000 行上限只剩 12 行 ⇒ E75 若要在本文件继续加代码必须先拆模块，不能硬塞。

- 2026-11-23 **74.3 built**：实现子会话在 25 次迭代处超限退出（未回报），留下**完整模块拆分**（新建 `network/ws_commands.py`、四个端口契约迁入 `ws_protocol.py`、两个命令循环的 `cancel_run` 分支）但未写测试、未落 plan；宿主接手补 `tests/network/test_ws_cancel_run.py`（6 例）、`test_ws_protocol.py` 3 组帧面判据 + `typing` 导入白名单、封闭命令集断言，逐条实测后 `mark 74.3 built`。验证：`pytest tests/network tests/test_architecture_contracts.py -q` = 685 passed；`pytest tests/network/test_ws_cancel_run.py tests/network/test_ws_protocol.py -q` = 38 passed；`pytest tests/test_cli_http.py tests/test_cli_http_lifecycle.py tests/test_http_web_ui.py -q` = 171 passed / 34 skipped（无 node 的前端探针）；ruff / format / mypy / bandit 全绿。
- 2026-11-23 Decision: `ws_server.py` 拆前 988 行、本 entry 至少加 40+ 行 ⇒ 先拆再改：新建 `network/ws_commands.py` 承载命令循环簇（`_send_error*` / `_next_command` / `_handle_commands` / `_submit_run` / `_start_project_run` / `_handle_submit_commands`），四个端口契约（`WebSocketLike` / `RunWebSocketService` / `SubmittedRun` / `ProjectChannelService`）迁入 `ws_protocol.py`；依赖单向 `ws_server → ws_commands → ws_protocol`，`ws_server.__all__` 与既有对外名一个不少。行数：698 / 253 / 425。
- 2026-11-23 Decision: 74.3 的 `write_set` 实际扩了 2 条 —— `src/heagent/network/ws_commands.py`（拆分产物）与 `tests/test_architecture_contracts.py`（`test_ws_endpoints_and_commands_stay_closed` 的封闭命令集断言必须随 `cancel_run` 同步，否则恒红）。本 entry 无 `parallel_group`、串行执行，不参与并行批，无写集相交风险。
- 2026-11-23 Decision: 集合级端点的 `unknown_run` **不断连**、单 run 端点沿用既有 `_send_error(close_code=POLICY)` 断连 —— 后者那条连接的唯一目标都不存在，继续留着没有意义；这是刻意的分层差异，不是漏改。
- 2026-11-23 Decision: CLI 旁路与通知流的命令循环把 `cancel_run` 与 `cancel` 同档拒绝（旁路 = 终端才拥有运行；通知流 = 无可取消对象），文案沿用各自既有句，未新增文案。

- 2026-11-23 **74.4 built**：宿主直接实现（本 entry 预期零 src 改动、单文件测试）。新增 `tests/network/test_ws_event_contract.py` 7 例：`WsEventFrame` / `WsAckFrame` 字段集合、`WsFrameType` 五档封闭、golden 事件信封**逐字**相等、事件面**两层**（帧层 + `RunEventPayload` 负载层）拒绝 `project_id`、WS 路由集与 `transport_routes.json` 的 `ws_host.py` 段逐字一致。验证：`pytest tests/network tests/test_architecture_contracts.py -q` = 692 passed；`pytest tests/network/test_ws_event_contract.py -q` = 7 passed；ruff / format / mypy 全绿。
- 2026-11-23 **已知预期红（不属本批）**：`tests/test_contract_baselines.py` 的两条 check 用例自 74.1 起就红 —— `exception_types.json` 基线里没有 74.1 新增的 `SubmittedRun` / `ProjectChannelService`（基线最后更新于 `7e2a9a6e`，2026-11-21）。重生成快照是 **76.6** 的交付（epic-74 Boundaries 明确「不重生成契约快照」），届时 `diff` 只应含这些预期新增；Step 07 的逐 entry 门禁（`tests/network` + 架构契约）不受影响。

- 2026-11-23 **74.5 built**：宿主直接实现（预期零 src 改动、单文件测试）。新增 `tests/network/test_ws_error_codes.py` 17 例：七条 code 逐条断言是 `HttpErrorCode` 既有成员 + 逐条在 `transport_errors.json` 有对应项；`network/` 对运行栈/配置面**导入面**零命中（AST，含 `TYPE_CHECKING`）、`is_dir` 零命中、五个 WS 模块都不导入 `http_server`。验证：`pytest tests/network tests/test_architecture_contracts.py -q` = 709 passed；单文件 17 passed；ruff / format / mypy 全绿。**E74 五条 entry 至此全部 built。**
- 2026-11-23 Decision: 74.5 的 `verify` 里「六条 `content_search` 断言 0 命中」按**AST 导入面**实现，不按纯文本 —— 实测 `network/` 里 `heagent.config` 有 5 处、`heagent.engine` 有 4 处命中，全是 docstring/注释里的说明性引用（「镜像 ``heagent.config.catalog`` 的同名常量」「不得 import ``heagent.engine.tasks``」），纯文本搜会把正当注释判成违规。`is_dir` 仍按文本断言（实测 0 处）。

## 交接块（下一轮入口）

- 下一条：`none（E74 五条全 built ⇒ 转 E74 收口三审 R1 → R2 → R3 → 回顾 → 提交）`；收口完成后 `tickets.py next` 的下一条是 E75 的 `75.1`
- 票树实测：`status docs/Goal-4` → counts {total: 17, review: 5, planned: 12}、E74 五条全 `built`、unpinned/undeclared/order_conflict 全空；`next.ready_to_start` = []（E75/E76 仍被 epic-level `after` 拦住）
- 必读：epic 文件 `docs/Goal-4/tickets/epic-74-ws-frame-contract/epic-74-ws-frame-contract.md`（Requirements R1–R7 / Done when）· 五份 plan（`story-e74-s01…s05-*-plan.md`）· 本 epic 的合并 diff（`git log --oneline d6e705de^..HEAD -- src/heagent/network tests/network`）
- 未关闭的门：**E74 收口三审未开跑**（R1 规格对账 / R2 不变量与守卫反脆弱 / R3 code_review 三镜头）；三份报告落 `tickets/epic-74-ws-frame-contract/epic-74-ws-frame-contract-review-r{1,2,3}.md`，回顾落 `…-retrospective.md`（带 `## 三审记录`）
- 本轮结论：E74 的交付面已闭合 —— 命令面 4 值（run / cancel / cancel_run / ping）、`cancel_run` 与 `cancel` 共用 `service.cancel_run` 端口、事件面逐字节未动（golden 信封 + 两层 `project_id` 拒绝 + 路由集对基线）、错误码零新增、`network/` 导入面零命中；`ws_server.py` 698 行（拆出 `ws_commands.py` 253 行）⇒ E75 加代码仍有余量。**已知预期红**：`tests/test_contract_baselines.py` 的 check 用例（`exception_types.json` 缺 74.1 新增的 `SubmittedRun` / `ProjectChannelService`）由 76.6 重生成快照收口。
