# goal 进度：Goal-4

- 目标：WS 远程项目通道（多项目控制）
- Initiative：Goal-4（goal 目录本身即 initiative 根，Step 04 写定）
- 状态：done（2026-11-24 E78 放行；Step 08 已于 2026-11-23 放行，E77 / E78 属重开增量）
- 当前步骤：全部完成（01–08 + E77 重开增量）

## 步骤状态

| 步骤 | 名称 | 状态 | 产物 |
|---|---|---|---|
| 01 | market-research | completed | `step-01-market-research/report.md` |
| 02 | brainstorm-options | completed | `step-02-brainstorm-options/report.md` |
| 03 | analyze-requirements | completed | `step-03-analyze-requirements/report.md` |
| 04 | define-product-scope | completed（approved 2026-11-23） | `prd-ws-remote-project-channel/prd-ws-remote-project-channel.md` + `tickets/`（3 个 epic） |
| 05 | design-architecture | completed | `architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md`（8 条 AD / 10 条不变量） |
| 06 | refine-stories | completed（approved 2026-11-23） | `tickets/<epic>/tickets/tickets.toml`（17 条 entry）+ `step-06-refine-stories/report.md` |
| 07 | implement-story | completed（E74 5 / E75 6 / E76 6 全部 built；E74/E75 收口三审 + 回顾） | 各 entry 的 plan（`tickets/<epic>/tickets/story-*-plan.md`） |
| 08 | system-integration-test | completed（approved 2026-11-23） | `step-08-system-integration-test/report.md` + 三份 `<E编号>-<slug>-integration-report.md` |

## Epic 与 entry（Step 06 后维护，状态抄自 `tickets.py status`）

- E74 `epic-74-ws-frame-contract`：5 entry 全部 built，epic 容器 `status: done`（2026-11-23 收口：三审 R1/R2/R3 + 回顾）
- E75 `epic-75-project-channel-runtime`：6 entry 全部 built，epic 容器 `status: done`（2026-11-23 收口：三审 R1/R2/R3 + 回顾）
- E76 `epic-76-remote-surface-closeout`：6 entry 全部 built，epic 容器 `status: done`（2026-11-23 收口：三审 R1/R2/R3 + 回顾 + Step 08 集成通过）
- E77 `epic-77-remote-contract-hardening`：3 entry 全部 done（77.1 幂等键 / 77.2 具名码 / 77.3 只读能力面与收口），epic 容器 `status: done`（2026-11-24 用户 `approve e77`；回顾见 epic 目录 `-retrospective.md`，**三审 R1/R2/R3 未跑**，见交接块）
- E78 `epic-78-open-items-followthrough`：3 entry 全部 done（78.1 幂等窗口可观测 / 78.2 `web_search_smoke.py` / 78.3 三条台账操作卡），epic 容器 `status: done`（2026-11-24 用户放行；三审单文档三镜头 + 回顾见 epic 目录）
- E79 `epic-79-a76-attest-tool`：2 entry 全部 done（79.1 `scripts/ws_tls_attest.py` 四段承兑 / 79.2 A76 操作卡收窄 + `AGENTS.md` 工具链指针），epic 容器 `status: done`（2026-11-24 用户 `approve e79`；三审单文档三镜头 + 回顾见 epic 目录）
- 合计 `counts {total: 25, done: 25}`（E79 两票 `mark done` 后实测）；`unpinned_after` / `undeclared_after` / `order_conflict` 全空
- `next` 实测（2026-11-24 E79 放行后）：五个 epic 容器全部 `done`、`longest_remaining_chain` 空（initiative 级 `status` / `next` 仍报 `config_utils.py` 缺失，属既有布局问题）

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

## 决策日志（Step 08 放行）

- 2026-11-23 Decision: 用户回复原文 `approve`（承接「Step 08 报告已呈报」）⇒ 按契约把 E74（5 条）+ E75（6 条）entry 逐条 `mark done`（E76 六条已于 2026-11-23 早前 approve 置 done），`progress.md` 状态置 `done`。三棵票树 `tickets.py status` 实测 `{E74: 5 done, E75: 6 done, E76: 6 done}`，`problems` / `unpinned_after` / `undeclared_after` / `order_conflict` 全空。

- 2026-11-27 **代码审查落改（用户指令「审查代码」→「改」→「提交」，提交 `73f9518d`）**：审查面 = 近 5 个
  代码 / 脚本提交（`bb971c03` 六处缓存面、`64e0c519` 项目通道提交超时上界、`a010faf3` story 引用保留、
  `8c72942a` cpolar 三脚本、`50d6e654` conftest 凭据密封），结论 **0 Critical / 0 High / 3 Medium / 9 Low**。
  当轮落改 7 处：① `docs/errors.md` 的 `timeout` 从「保留码·当前无发送点」改为真实口径（唯一发送点 =
  `ws_project_adapter`，超时结果未知）；② `docs/frame/network.md` 补项目通道提交上界（构造期 `submit_timeout`
  默认 30s）+ `docs/frame/cli.md` 适配器行去掉「只翻译不含判据」；③ `docs/performance.md` 与
  `docs/frame/providers.md` 的提示词缓存理由改写（system 尾部含 per-run / per-prompt 易变块 ⇒ system 断点
  几乎每轮 miss，稳定前缀是 tools；断点上限 4 个而非「多打就被拒」）；④ `scripts/cpolar_publish.py` 的
  `--watch` 回填失败不再记忆（下一轮重试）、隧道目标回退统一 `127.0.0.1`、日志按 BOM 判 UTF-16；
  ⑤ 三条边界 docstring（幂等窗口 `submit_timeout < ttl` 耦合 / 会话备忘录 FIFO 适用区间 / 静态资源 ETag
  整串精确比较）；⑥ `goal/worktree.py` 新增 `drop_story_ref`（放弃 story 时回收 gc 锚点，幂等 + 判据）；
  ⑦ `ws_commands._submit_run` 码清单补 `timeout`。**未修而升台账 2 条**：A77（`except TimeoutError` 捕获面
  偏宽，内层超时会被改写成 30s 文案）、A78（cpolar 地址回退无活性校验，死地址可能被 `--apply` 写进 App）。
  门禁：`ruff` / `ruff format --check` / `mypy` 净、9 个测试面 `292 passed`、契约快照五份 `[OK]`、
  `mkdocs --strict` 0 WARNING、台账守卫 8 passed；**未 push**。

- 2026-11-27 **A77 / A78 当轮闭合**（用户指令「2 3」= 直接动手这两条）：**A77** 上界仲裁从
  `asyncio.wait_for` 改为 `_bounded` 的 `asyncio.wait`（pending 才判 `timeout` 码，内层 `TimeoutError`
  原样透传 ⇒ 骨架 `server_error`），行数预算 150 → 180 并写明理由；**A78** `cpolar_publish.py` 新增
  TCP 活性闸门 `verified_address`（管理面与 `--address` 免探，其余回退来源连不上即拒写、退出码 1；
  `watch` 不过闸门不前进游标）。判据：`tests/test_ws_project_adapter.py` 41 passed（新增 1 例内层超时
  不代译）、`tests/test_cpolar_publish.py` 12 passed（新文件）；两条各做变异自证（注入后转红、复原转绿）。
  台账：A77 / A78 迁 `retrospective-all-cycles.md` §三「本轮闭合（2026-11-27 …）」，活动项 5 → 3，
  三处计数同步；`tests/test_deferred_id_registry.py` 8 passed。

- 2026-11-27 **审查剩余 Low 收口**（用户指令「2」= 处理未落地的 Low）：**Low 8** 静态资源 ETag 命中
  判定抽成 `_etag_matches`，按 RFC 9110 §13.1.2 认多值列表 / `W/` 弱校验符 / `*`（原先整串比较 ⇒
  CDN / 代理改写 ETag 会静默失去 304）；**Low 2** 会话备忘录首次**饱和**打一条
  `session event=metadata_memo_saturated entries=1024 dir=…`（WARNING，只打一次）——饱和 = 会话数已超
  上限、被挤掉的尾部每轮重解析，是性能拐点而不是错误，此前完全不可见；**Low 7** `promote_story_commit`
  的冲突报错补「放弃 story 时用 `drop_story_ref` 回收」的显式出口。**Low 1 不改代码**：探测失效需要
  `submit_timeout ≥ ttl`（现默认 30s < 60s），且退化后代价是 ≤256 条 dict 扫描（微秒级），docstring 已把
  耦合写死。判据：`tests/network/test_http_server.py`（新增 2 例：命中三形态 / 不命中四形态）、
  `tests/test_session.py::test_memo_saturation_warns_exactly_once`、
  `tests/test_story_worktree.py`（冲突报错断言补 `drop_story_ref`）；前两条各做变异自证（注入后转红、复原转绿）。

## 交接块（下一轮入口）

- 下一条：**无** —— E77 三条 entry 全部 `done`、epic 容器 `status: done`，Goal-4 合计 4 epic / 20 entry 全 done。
- 票树实测：E74 `{5 done}` / E75 `{6 done}` / E76 `{6 done}` / E77 `{3 done}`，`problems` 全空；合计 `{total:20, done:20}`。
- **构建轮差异已补齐**：E77 构建是单 lane + 用户直批（当时没跑三审）；**2026-11-24 已补跑 R1/R2/R3**，
  三份报告落 `tickets/epic-77-remote-contract-hardening/epic-77-remote-contract-hardening-review-r{1,2,3}.md`
  （契约面 / 并发面 / 文档面），落改 8 处已进工作树，等提交。
- 质量门禁（E77 三审落改后实测）：全量 `pytest` 5899 passed / 0 failed；`ruff` / `format` / `mypy 242` / `bandit` 干净；
  五份契约基线 `[OK]`；`mkdocs build --strict` 0 warning；docs 守卫 20 passed。
- 恢复入口：读本节 + `brief.md` 延期项（三条已裁决，无未裁决项）+ `tickets/epic-77-remote-contract-hardening/`。

- 2026-11-24 进度表校正：E76 行与合计 / `next` 行按 `tickets.py status` 实测更新（6/6 done、total 17 / done 17、无 ready_to_start 与 blocked）；只改事实与状态行，不改历史 Decision 条目。


- 2026-11-24 Decision（三条延期项裁决，用户回复「1 B 按推荐」）：`brief.md` 延期项三条逐条落定 ——
  - R3 M-4（提交幂等）取**最小幂等**形态：`run` 帧加可选 `request_id`，适配器做 60s / 256 条内存窗口，在途合流 + 成功结果重放，失败不缓存；不落盘、不跨进程（显式边界）。
  - R3 M-7（错误码分流）取**新增具名码**：`project_channel_unavailable` 只给「项目通道未装配」两条路径用，帧拼错仍 `invalid_request`；`HttpErrorCode` 36 → 37，`transport_errors` 基线只增一条。
  - E75 H-2（只读 listener 项目清单）取**维持零能力面**：只读 listener 不注册集合级端点 ⇒ `projects` 不可达，改 AD-8 措辞与代码对齐，不新开端点（该档位自 Epic 72 起无入口层配置键）。
  - 落点：`docs/Goal-4/tickets/epic-77-remote-contract-hardening/`（3 entry）。

- 2026-11-24 Decision（E77 放行）：用户回复原文 `approve e77` ⇒ 按契约把 77.1 / 77.2 / 77.3 逐条 `mark done`，
  epic 容器 frontmatter 置 `status: done`，goal 状态回 `done`。本轮构建为单 lane，**三审 R1/R2/R3 未跑**
  （用户在报告页直接 approve），差异已写进交接块，供下一轮决定是否补审。

- 2026-11-24 **E77 补跑三审（用户：「3」= 补三审 R1/R2/R3）**：评审对象 = 未提交工作树（`HEAD 669ed177`）。
  R1（规格对账）有条件的通过：C0 / H0 / **M1** / L2，M1 = `docs/errors.md` 传输层码计数差一（写 36、实际 37，
  HEAD 时已是 35 vs 36 的旧偏差，本 epic 顺着 +1 未修）⇒ 落改 37 / 78（异常类 29、CLI 12 两条已核对自洽）。
  R2（不变量与守卫反脆弱）有条件的通过：C0 / H0 / **M2** / L2。M1 = `asyncio.shield` **零判据**且 docstring 把失败模式
  写成 `InvalidStateError`（实测被 `if not future.done()` 守卫挡掉，真实现象是**兄弟合流者收到 `CancelledError`**）⇒
  改写 docstring + 补连坐取消用例（去掉 shield 即红）。M2 = 在途项会被 TTL 过期 / 容量淘汰**踢出** ⇒「在途合流」
  有静默空洞（实测 61s 后在途同键 `is_owner=True`、`max_entries=2` 时最旧在途被淘汰）⇒ 落改「过期只清已完成项 +
  容量满优先淘汰已完成项」，新增 `tests/test_ws_submission_cache.py` 5 例。L2 = 同键不同 prompt 静默重放第一次结果
  ⇒ 写成显式边界（键不含 prompt，服务端不比对载荷）。
  R3（三镜头对抗式）通过：C0 / H0 / **M2** / L3，两条 Medium 都是**同一文档内自相矛盾**——架构 §7 第 7 条仍写
  「`projects` 在只读 listener 上开放」（与 AD-8 更正相反）、第 1 条仍写「提交命令无幂等键 … 不在本 epic 范围」
  （E77 R1 就是闭合它）⇒ 两条都按裁决改成闭合态并显式写出残余边界；L = `brief.md` 表头「两条」与正文三条不符、
  架构三处指向不存在的 `docs/frame.md` 与两处「四份基线」（现行五份）⇒ 全部落改。
  五条注入反证（A 连坐取消 / B 在途不过期 / C 帧可选性 / D 失败移出窗口 / E `network/` 零命中幂等窗口）全部
  「红 → 复原 → 绿」。落改后门禁：全量 `pytest` 5899 passed / 0 failed、`ruff` / `format`（512 files）/ `mypy 242` /
  `bandit` 干净、五份基线 `[OK]`、`mkdocs --strict` 0 warning。**工作树当前有未提交改动，等用户放行提交。**

- 2026-11-24 **E77 提交后代码复审（用户：「3」= 审查这轮已提交代码）**：对象 = `95945586`，报告落
  `tickets/epic-77-remote-contract-hardening/epic-77-remote-contract-hardening-review-r4.md`。
  C0 / H0 / **M2** / L3。M1 = `request_id` 不带 `project_id` 时被**静默忽略**（探针实测：同帧重发两次
  `start_run` 2 次、ack 两个 run_id）⇒ 不改行为、把边界写进帧模型 / 命令层 docstring 与 framework 提交 run 行，
  并补判据 `test_request_id_without_project_id_never_reaches_the_idempotency_window`。
  M2 = 文档口径「60s / 256」无判据且两个常量无人消费 ⇒ 补 `test_window_defaults_match_the_documented_numbers`
  （常量 == 文档数字、构造默认 == 常量；注入把 60.0 改 30.0 ⇒ 2 failed）。
  L1 = WS `request_id`（幂等键）与 HTTP `request_id`（`x-request-id` 追踪）同名不同义 ⇒ 文档同句消歧（已落改）；
  L2 = `if not future.done()` 正常路径不可达（保留作防御，它是 R2-M-1 docstring 误述的成因）；
  L3 = 同一句错误文案两处硬编码（三行以内重复，按既有立场不抽）。落改后门禁：目标子集 978 passed、
  `ruff` / `format`（512）/ `mypy 242` 全绿、五份基线 `[OK]`、`mkdocs --strict` 0 warning。

- 2026-11-24 **E78 立项并构建（用户：「在本 goal 继续 1 2 3」）**：台账 4 条活动项实测全等外部触发（A67 无 docker
  daemon / A55 无 key 且无脚本 / A76 宿主 netstat 与客户端 pin 在仓外 / A65 用户裁定暂停），故只做仓库内三件，
  进票树登记为 `docs/Goal-4/tickets/epic-78-open-items-followthrough/`（3 entry，`counts {3 done}`）。
  ① 78.1 幂等窗口可观测：`SubmissionCache` 加两条 DEBUG 事件（`idempotency_evicted reason=capacity` /
  `idempotency_dropped reason=failed|cancelled`），`drop(key, *, reason=…)`，适配器两处传对 reason；日志只带
  `project_id`、`request_id` 不进日志、TTL 清理静默；判据 5 例（含 caplog 断言与「日志里无 `request_id`」），
  注入反证 = 删掉 evicted 那行 ⇒ 1 failed。**不新登 A77**（立完即闭合的 A 号只增加迁移成本），闭合证据写进
  E77 回顾原「可观察但未做」那条。② 78.2 `scripts/web_search_smoke.py`：四段判据（config / 引擎真调用 /
  工具面截断 / 注入围栏）+ `--self-check` 离线自检 + 退出码 0/1/2 契约；key 只报「已配置（长度 N）」；
  4 例判据（离线自检 exit 0 / 无 key exit 2 / `--help` / 「取 key 的行不得是输出行」静态断言）。
  ③ 78.3 A55 / A67 / A76 三条台账正文各补「操作卡」（命令原文 + 期望输出 + 回填位置），活动条数仍 4、
  ID 集合不变；`tests/test_deferred_id_registry.py` 全绿（其间被表格竖线绊过一次：`netstat -ano | findstr`
  的 `|` 会拆单元格，改成「`netstat -ano`（再用 `findstr` 过滤）」）。

- 2026-11-24 **E78 收口三审（用户：「2 三审合并为一个文档，以后也一样」）**：形态按裁定改为**单文档三镜头**
  （`epic-78-open-items-followthrough-review.md`），`closeout.md` 同步（历史 epic 的三份不动）。
  镜头一（规格对账）**通过** C0/H0/M0/L0：R1–R3 与 Done-when 四条逐条成立。镜头二（不变量与守卫反脆弱）
  **有条件的通过** C0/H0/**M2**/L0，两条 Medium 都是冒烟脚本自身的判据缺陷、当轮落改：M1 = 条目解析按行首
  `[n]` 数行，摘要是多行时会把摘要里的伪造行误计成第 6 条 ⇒ A55 闭合路径上的**假 FAIL**（探针实测 5 条被读成 6 条）⇒
  改「空行分块 + 块首行匹配」并补 2 例；M2 = 段 2 文案写「0 条不算失败」而代码 `seg.check(bool(results))` 判 FAIL ⇒
  0 条改 `note`。镜头三（契约 / 并发 / 文档）**通过** C0/H0/M0/**L1**：不新增码/不开基线漂移、日志只在真删除时打、
  台账操作卡命令与 `--help` 实测一致；L1 = 无 key 时报告 `[FAIL]` 与 exit 2 并存（语义以退出码为准，记录不改）。
  **七条注入反证**全「红 → 复原 → 绿」（删 evicted 日志 / 取消路径 reason 写死 / TTL 也打日志 / key 塞进输出行 /
  evicted 日志带 request_id / 条目解析退回按行数 / 0 条判 FAIL）。门禁：全量 `pytest` 5910 passed / 0 failed、
  `ruff` / `format`（539）/ `mypy 242` 干净、五份基线 `[OK]`、`mkdocs --strict` 0 warning、
  `loop` 技能自检 `PASS=17 FAIL=0`。**工作树仍未提交，等放行。**

- 2026-11-24 Decision（E78 放行）：用户回复原文 `2 3`（在编号候选里选「放行 E78 收口」+「挑下一项」）⇒ 按契约把
  78.1 / 78.2 / 78.3 逐条 `mark done`（实测 `counts {total: 3, done: 3}`），epic 容器 frontmatter 置 `status: done`，
  goal 状态回 `done`（`status` 实测 `done`）。放行前复跑锚点判据：`tests/test_ws_submission_cache.py` +
  `test_ws_project_adapter.py` + `test_web_search_smoke_script.py` + `test_deferred_id_registry.py` +
  `test_architecture_contracts.py` = **101 passed**（13.96s），与 `080c8471` 提交信息里的门禁记录一致。

- 2026-11-24 **E79 立项并构建（用户回「3」= 修文档漂移 + 写承兑脚本一起做，并顺带改 A76 台账正文）**：
  进票树 `docs/Goal-4/tickets/epic-79-a76-attest-tool/`（2 entry，`counts {2 built}`）。
  ① 79.1 `scripts/ws_tls_attest.py`（stdlib only）四段承兑：绑定面（被测地址可连 + 默认要求 `127.0.0.1:<port>`
  REFUSED）/ TLS 握手（版本 + 套件 + 对端叶证书，刻意不校链不校主机名）/ pin 对账（对端 SPKI == `--cert`，
  打印 `spki_sha256` + 短指纹 + `sha256/<base64>` 三格式）/ 认证闸门（无 token 期望 403，`--token` 追加验 101）；
  可选 `--status-url` 第 ⑤ 段比对 `/api/status` 的 `tls.spki_sha256`；退出码 0/1/2；`--self-check` 进程内起 TLS stub
  离线自证四段，`--serve-cert` 专供「对端与本地材料不是同一套」的判红路径。判据 7 例（自检全绿 / 换证书判 1 且含
  `pin 漂移` / 材料缺失 exit 2 / 目标未监听 exit 2 / `--help` / token 静态断言 / IPv6 脱括号）。
  **真跑生产姿态**：`192.168.2.226:9201` 四段全 `[OK]`、exit 0，`127.0.0.1:9201 REFUSED`、
  pin `247a8b…fd301`（`ER5I-WJUT-A7JP`）、`无 token → HTTP/1.1 403`。
  ② 79.2 A76 操作卡把「宿主 `netstat` + `heagent tls fingerprint` 两条手工命令」收成「跑这一条 + 期望输出」，
  `netstat` 降为可选补证；`AGENTS.md` 工具链序列补 `ws_tls_attest.py`（`heagent tls` → attest → `ws_manual_probe`）。
  `docs/tls-connect-guide.md` 的漂移（引已退役 A75、写「生产姿态未切换」、「第一步（现行）」）**已在本地页修正**，
  但该页被 `.gitignore` 排除（ADR-0004：客户端本地资料）⇒ 不入库，故 79.2 的 write_set 不含它。
  门禁：全量 `pytest` 5872 passed / 0 failed（65 skipped = 本会话 PATH 无 node）、
  `ruff check` + `format --check`（299 files）、`mypy src`（242 files）干净、`mkdocs --strict` 0 warning、
  台账与链接守卫 27 passed。**工作树未提交，等放行。**

- 2026-11-24 **E79 收口三审（单文档三镜头）+ 落改**：审查对象 = 未提交工作树（`HEAD 767f54b2` + 8 项）。
  ① 镜头一（规格对账）R1/R2 逐条对读全成立，0 条发现；真跑生产姿态四段 `[OK]` / exit 0，与 A76 操作卡三行
  期望输出逐字一致。② 镜头二（反脆弱）挖出 4 条 Medium 并当轮落改：
  **M-1** 暴露面漂移（期望拒绝却 OPEN）原被当成「服务未在监听」→ `exit 2` + 误导文案，改为
  `_segment_bind` 返 `(seg, reachable)`、漂移走 `1`；**M-2** `_split_host_port` 自写 `strip("[]")`（第四份
  脱括号实现，且把 `[localhost]` 也剥掉）→ 改走 `network.exposure.unbracket_host`；**M-3** 第 ⑤ 段从人读
  文案 `rsplit("：")` 反解析指纹 + 无叶证书时 `"" in seen` → 改 `_segment_pin` 显式返回 `remote_sha`、
  缺指纹判红；**M-4** 本地材料不可解析（`TlsIdentityError`）与 `--refused` 非法串（`ValueError`）都退化成
  traceback 且 `rc=1`（应 `2`）→ 前置解析 + 「参数错误」。另有 L-1 `tls.cipher()` 双调、L-2 `ws_listeners`
  幻影别名顺手落改；L-3 常量重复 / L-4 真机 101 本环境不可验（用户级 token 不在容器）/ L-5 协议下限由
  uvicorn 兜底，三条记录不改。③ 判据 7 → 11 例（漂移判 `1` / 材料不可解析判 `2` / `--refused` 非法判 `2` /
  第 ⑤ 段显式指纹判据），7 条注入反证全部「红 → 复原 → 绿」。④ 门禁：全量 `pytest`（带 node）
  **5924 passed / 0 failed**（336s）、台账与链接守卫 72 passed / 1 skipped、`ruff check` + `format --check`
  （553 files）、`mypy src`（242 files）、`contract_snapshot --check` 五份 `[OK]`、`mkdocs --strict` 0 warning。
  **工作树仍未提交，等放行。**

- 2026-11-24 **E79 放行（用户 `approve e79`）**：两票 `mark done`（`tickets.py status` 实测
  `counts {total: 2, done: 2}`、`longest_remaining_chain` 空），epic 容器置 `done`；回顾写进
  `epic-79-a76-attest-tool-retrospective.md`。goal 级合计 `{total: 25, done: 25}`，五个 epic 全部收口。
  **A76 仍不闭合**：剩客户端 `X509TrustManager` pin 与设备三处对账（`aihome-client` 仓），服务端侧已机器化
  （`python scripts/ws_tls_attest.py` 一条命令四段 `[OK]`）。
