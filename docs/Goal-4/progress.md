# goal 进度：Goal-4

- 目标：WS 远程项目通道（多项目控制）
- Initiative：Goal-4（goal 目录本身即 initiative 根，Step 04 写定）
- 状态：in-progress
- 当前步骤：step-07-implement-story（E74 / E75 均已收口；下一步 = E76 首批 76.1–76.4）

## 步骤状态

| 步骤 | 名称 | 状态 | 产物 |
|---|---|---|---|
| 01 | market-research | completed | `step-01-market-research/report.md` |
| 02 | brainstorm-options | completed | `step-02-brainstorm-options/report.md` |
| 03 | analyze-requirements | completed | `step-03-analyze-requirements/report.md` |
| 04 | define-product-scope | completed（approved 2026-11-23） | `prd-ws-remote-project-channel/prd-ws-remote-project-channel.md` + `tickets/`（3 个 epic） |
| 05 | design-architecture | completed | `architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md`（8 条 AD / 10 条不变量） |
| 06 | refine-stories | completed（approved 2026-11-23） | `tickets/<epic>/tickets/tickets.toml`（17 条 entry）+ `step-06-refine-stories/report.md` |
| 07 | implement-story | in-progress（E74 / E75 已收口；续跑 E76 六条 entry） | 各 entry 的 plan（`tickets/<epic>/tickets/story-*-plan.md`） |

## Epic 与 entry（Step 06 后维护，状态抄自 `tickets.py status`）

- E74 `epic-74-ws-frame-contract`：5 entry 全部 built，epic 容器 `status: done`（2026-11-23 收口：三审 R1/R2/R3 + 回顾）
- E75 `epic-75-project-channel-runtime`：6 entry 全部 built，epic 容器 `status: done`（2026-11-23 收口：三审 R1/R2/R3 + 回顾）
- E76 `epic-76-remote-surface-closeout`：6 entry，0 built（收口 E75 后解锁）
- 合计 `counts {total: 17, review: 11, planned: 6}`；`unpinned_after` / `undeclared_after` / `order_conflict` 全空
- `next` 实测（E75 收口后）：`ready_to_start` = `76.1` / `76.2` / `76.3` / `76.4`；`blocked` = `76.5`（waiting 1,2）/ `76.6`（waiting 1,2,4,5）

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

- 2026-11-23 **E74 收口三审（新会话开跑，R1 → R2 → R3 连跑）**：三份报告落 `tickets/epic-74-ws-frame-contract/epic-74-ws-frame-contract-review-r{1,2,3}.md`。R1（规格对账）有条件的通过：5 条已交付 / 2 条部分（R2 声明位置、R5 两处口径差），Critical 0 / High 0 / Medium 2 / Low 8 → 全进延期项，无落改。R2（不变量与守卫反脆弱）有条件的通过：Critical 0 / **High 1** / Medium 3 / Low 2，High = 依赖边界守卫对**相对导入**无牙（`from ..config import ...` 在 `network/` 里两条守卫双绿），当轮修补并把「HEAD 无牙 → 修补后有牙 → 无注入转绿」写成反证 D。R3（三镜头对抗式）通过：唯一 high（H-1 说 `_package_of` 产生 `heagent.heagent.*`）经宿主实测为**误报**（评审把 `SRC/'heagent'/...` 多传了一层），真实接线注入相对导入后 `test_no_reverse_dependency_on_agent` 报 `运行期反向依赖：network/ws_commands.py → heagent.config`，复原即绿；medium 8 条落改 3（M-2 端口异常漏译判据 / M-5 ack 语义措辞 / M-6 `project_service` 显式忽略），low 6 条落改 5。
- 2026-11-23 Decision: 三审落改共 **8 处** —— 新增判据 6 例（端口异常漏译、`cancel_run` 断连分支钉子、ack 如实回执 `running`、`project_id` 17 字符上界、非对象 JSON 四例参数化、两条只读流 `cancel_run` 拒绝）+ 收紧 R4 判据（删 `unmapped_codes` 逃生门）+ 两处 src 措辞/信号（`ws_commands.py` 的 ack 语义、`ws_server.py` 的 `ws event=project_service_ignored` debug）。
- 2026-11-23 Decision: epic 容器 `status: done` 由宿主在收口时写进 epic 文件 frontmatter（`tickets.py mark` 只管 entry）。理由：`classify()` 的 epic gate 只认「容器 status == done」，不写则 `after: [epic-74]` 的 E75 / E76 永久 blocked（epic 级 `after` 声明因此无法自洽）。entry 的 `done` 仍只由 Step 08 的人工 `approve` 写。
- 2026-11-23 **E74 收口门禁实测**：`pytest tests/network tests/test_architecture_contracts.py -q` = **719 passed**；`pytest tests/network -q` = 679 passed；`ruff check` / `ruff format --check`（499 files）/ `mypy src`（239 files）/ `bandit -r src/ -ll`（No issues identified）全绿。`pytest tests/test_contract_baselines.py` 仍 2 红（`exception_types.json` 缺 74.1 新增的 `SubmittedRun` / `ProjectChannelService`）——**已知预期红**，76.6 重生成快照收口。
- 2026-11-23 **E74 收口提交**：`test(e74-s05): 依赖边界守卫补齐相对导入与 AST 口径` + `fix(e74): 三审落改补判据与 ack 语义，E74 收口`。
- 2026-11-23 **E75 收口三审（R1 → 修 → R2 → 修 → R3 → 修 → 回顾）**：三份报告落 `tickets/epic-75-project-channel-runtime/-review-r{1,2,3}.md`。
  - **R1**（规格对账，`bmad-code-review` 镜头）有条件的通过：Critical 0 / **High 1** / Medium 4 / Low 7。High = R5 的「提交径 fail-loud 回 `project_registry_unreadable`」**无生产来源**（注册表坏 ⇒ `find()` fail-soft ⇒ `unknown_project`，正是架构文档的被拒替代 (c)）⇒ 落改：适配器 `_guard_registry` + 健康探针进线程池 + 真注册表两例；另补真注册表顺序与 31 条上限判据、`list()` docstring 口径、s06 plan 基线份数。
  - **R2**（不变量与守卫反脆弱，宿主自扫 + 三条注入反证）有条件的通过：Critical 0 / High 0 / Medium 3 / Low 4。Medium = 告警去重集只增不减 ⇒ 修好后再坏全静默 ⇒ 落改按故障期复位 + 用例；三条反证（命令集封闭 / `network` 无 `is_dir` / 新健康守卫）全部「红 → 复原 → 绿」。宿主复核纠正 R1 的一条误报：`network/` 的 `is_dir` 守卫早已存在（`tests/network/test_ws_error_codes.py:111`）。
  - **R3**（三镜头对抗式，`code_review`）放行：Critical 0 / **High 2** / Medium 10 / Low 15。两条 high 全是**规格文本自相矛盾**、非代码缺陷：H-1 = epic Boundaries「不改帧定义与错误码」与架构 AD 授权的新增帧/命令/码相反；H-2 = 架构 AD-8「只读 listener 上 `projects` 允许」与 §4.1 + E74 端点集矛盾（只读 listener 上零可达，实现落到的正是 AD-8 的被拒替代 (a)）⇒ 按 `bad_spec` 记规格缺陷 + KEEP，**不改冻结段、不改 E74 端点集**，H-2 的「是否需要只读项目清单」标为**需用户裁决**。
  - R3 的 Medium/Low 落改 6 处：`default` 豁免健康守卫、告警「删文件也复位」、帧界三处按 AD §4.2（`name` 1–64 / `projects` ≤32 / 默认 `ok`）、登记上限 32 → 31（消除 33 条溢出导致的 `server_error` + 断连）、非 UTF-8 与 schema 两分支补判据、`ws_commands` docstring。
  - 落改后门禁：`829 passed` / ruff / format / mypy / bandit / `mkdocs --strict` 0 warning / 契约基线五份 `[OK]`。
- 2026-11-23 **E75 收口结论**：epic 容器 `status: done` 写进 epic frontmatter ⇒ E76 六条解锁；回顾落 `-retrospective.md`（含 `## 三审记录`）。六条 entry 的 `done` 仍等 Step 08 的人工 `approve`。

## 交接块（下一轮入口）

- 下一条：**无** —— E76 六条 entry 已由 Step 08 人工 `approve` 全部置 `done`（`tickets.py status epic-76-remote-surface-closeout` → `{total: 6, done: 6}`），epic 容器 `status: done`；Goal-4 三条 epic（E74/E75/E76）交付面闭合。
- 票树实测：`status docs/Goal-4` → `{total: 17, review: 17}`、problems 空（E74/E75/E76 全 built）。
- **E76 收口三审（R1 → R2 → R3，本会话连跑）**：三份报告落 `tickets/epic-76-remote-surface-closeout/epic-76-remote-surface-closeout-review-r{1,2,3}.md`。
  - **R1**（规格对账）有条件的通过：Critical 0 / High 0 / Medium 4 / Low 3。口径差 2 条记 epic Notes（R2 的 `project_busy` 在生产 WS 链上实为 `run_conflict`；R7 快照是 5 份不是 4 份），延期项 4 条（`lan` 档零告警 / 回落链取请求值 / 端到端仍用端口替身 / 两处公告口径不一致），当轮落改 1 处。
  - **R2**（不变量与守卫反证）通过：G1–G7 全可反证。两条实跑反证 —— ① `_warn_external_without_sandbox` 注入 `return None` ⇒ `test_external_listener_on_a_non_docker_backend_warns_exactly_once` 红，回退绿；② `_assert_single_adapter` 补 `assert "sandbox_backend" in calls[0]` 前，「入口漏传」也能过（回落链掩盖）。
  - **R3**（三镜头）通过（有条件）：Critical 0 / High 0 / Medium 3 / Low 3，全转延期项。
- 当轮落改 **1 处**：`tests/test_cli_http_lifecycle.py` 的 `_assert_single_adapter` 增 `sandbox_backend` 注入断言（R6 判据必须取**生效**档位，不能靠回落值蒙过）。
- **E76 收口门禁实测**：`pytest tests/network tests/test_cli_http_lifecycle.py tests/test_architecture_contracts.py tests/test_contract_baselines.py tests/test_docs_links.py -q` = **795 passed**；`contract_snapshot.py --check` = 五份 `[OK]`；`mkdocs build --strict` 0 warning（9.14s）；`ruff check` / `format --check` / `mypy src`（240 files）/ `bandit -r src/ -ll`（No issues identified）全绿。
- 回顾落 `tickets/epic-76-remote-surface-closeout/epic-76-remote-surface-closeout-retrospective.md`（含 `## 三审记录`）。
- 2026-11-23 **E76 延期项全部回捞闭合**（用户裁决 1/2/3 连跑）：
  - ① `lan` 档补独立告警锚点：`_warn_remote_without_sandbox` 返回 `(锚点, 正文)`，`external` → `ws event=external_without_sandbox`、`lan` → `ws event=lan_without_sandbox`（文案点名「no token」，因为同网段任何设备都能驱使代理）；`docker` 档两档都 0 条。判据 `test_lan_listener_without_docker_warns_with_its_own_anchor` / `test_lan_listener_on_docker_stays_quiet`。
  - ② 回落链「静默窗口」经核**生产不可达**：`HttpAgentHandler.__init__` 无条件 `self.engine = engine or EngineContainer.default(...)`，而 `EngineContainer.default` 必写 `sandbox_decision` ⇒ `_effective_sandbox_backend` 在生产路径不含 None，`or sandbox or settings.sandbox_backend` 只服务注入替身。判据 `test_a_real_handler_always_reports_an_effective_backend`；`http.py` 的注释点明该尾巴的适用范围。
  - ③ ADR-005 端到端补**真 listener** 判据：新增 `tests/network/test_ws_remote_flow_live.py`（真 `WsServer` 随机端口 + 真 `HttpRunService` + 真 `HttpProjectConsole` + 真 `AgentLoop`，生产装配走 `_project_channel`）。两条用例覆盖：列项目帧 / 提交 / 取消到 `cancelled` 终态 / 跑到 `done` 终态（seq 连续）/ `last_event_id` 续流无空洞；以及「真 AgentLoop 跑完并落会话文件」。
- 未关闭的门：E76 无（延期项清零）。`brief.md` 里仍挂着 E74/E75 时代的既有延期项，与本 epic 无关。
- 本轮结论：ADR-005 验收基线在组合层面闭合（并发隔离 / cursor 续流 / 可见面不扩张 / 契约与文档收口），远程面「`external` 必须 wss + token，非 docker 后端每次启动喊一条」已落地；端到端真 listener 仍是已知缺口。
