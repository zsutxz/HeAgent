# Deferred Work——活动条目 + 闭合归档

> 本文件自 2026-09-17 起承接两类条目（原活动台账 `deferred-work.md` 已删除，用户裁定）：
> ① **活动（未闭合）条目**——工作流的 append-only 入口，闭合后按归属 epic 归档至各周期
> `deferred-work.md`（勘察类留在本文件，索引见 `consolidated-overview.md` 13.1）；
> ② **闭合归档**——正文分两处落（2026-09-24 起）：**勘察类**（source_spec 为勘察批次、无归属 epic）留在本文件；**有归属 epic 的**按规则回填到各周期 `deferred-work.md`（`Z-D10` / `Z-D11` → [`epic-48-TCP网络接口周期/deferred-work.md`](../epics/epic-48-TCP网络接口周期/deferred-work.md)，`Z-D13`~`Z-D15` → [`epic-50-网页控制台周期/deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md)）。本文件仍登记**全部 `Z-Dn` 的 ID 索引**（见下状态总览），但不保留已回填条目的正文副本。

## 活动（未闭合）条目——16 条

> **流水账单**（每次新增 / 闭合都往下接一行；本区**只留未闭合条目**——条目一闭合即连同正文移入下方「勘察类闭合归档」，不在本区留副本）
>
> - 2026-09-17：自活动台账 `deferred-work.md` 迁入 6 条
> - 2026-09-18：闭合 2 条 → Z-D8 / Z-D9
> - 2026-09-22：架构优化周期新增 2 条（本文旧编号 A7 / A8，现按下列顺序编号）
> - 2026-09-23：Epic 48 收口新增 3 条，其中「运行栈日志非观测故障免疫」「入口日志未脱敏」同日随可观测性与日志卫生批次闭合 → Z-D10 / Z-D11；代码评审新增 1 条，同日以 fail-soft 闭合 → Z-D12
> - 2026-09-24：Epic 50 规划评审新增 1 条（跨项目并发无全局上限——D9 采纳后的已知缺口，计划期登记，待 Epic 50 实现后复核）；Epic 50 收口评审新增 3 条（运行时归因与兜底族 / 控制台阻塞 I/O 与会话列表成本 / 非回环运行姿态**待裁决**；报告 `epics/epic-50-网页控制台周期/reviews/review-epic-50-implementation.md`）
> - 2026-09-24：Story 50-5 实现新增 2 条（写通道可把无上界的「资源旋钮」键设成极端值 / 审计文件无保留期上限），同日闭合 → Z-D13 / Z-D14；Story 50-6 实现新增 2 条（浏览器级 UI 验收不在 CI 且不含真实 LLM 运行 / 「高影响键的差异化确认」缺后端风险标记）；Story 50-6 收口后由用户实测发现并当日修复 1 条（首页加载即弹出关不掉的确认遮罩，`.overlay{display:flex}` 压过 `hidden` 属性）→ Z-D15；Epic 50 收口评审（第二轮）新增 1 条（写入通道与保真写的四类低危残余；报告 `epics/epic-50-网页控制台周期/reviews/review-epic-50-closure.md`）
> - 2026-09-24：**整理**——删除 5 条已闭合条目在本区的副本（Z-D10 / Z-D11 / Z-D12 / Z-D13 / Z-D14），正文并入下方同名小节（**Z-D12 小节此前缺失**，本次由副本改写补建）
> - 2026-09-24：**回填**——`Z-D10` / `Z-D11`（Epic 48）与 `Z-D13` / `Z-D14` / `Z-D15`（Epic 50）的**正文**按「归属 epic」移入各自周期 `deferred-work.md`（本文件只留 ID 索引，不再留副本）
> - 2026-09-24：**Story 50-8（Epic 50 收口后的体验优化轮）实现新增 2 条**——①「网页请求可拉起宿主 GUI 进程」的新暴露面（弹窗，有意引入，含不可用环境与「回环 ≠ 可信」口径）；②真实原生窗口的验收不可自动化 + 网页侧读取结果收敛所依赖的 `Error:` 前缀判据是展示层启发式。报告与实测见 `epics/epic-50-网页控制台周期/reviews/acceptance-50-8-refinement.md`

- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。
  Progress（2026-09-23 复核，**保持未闭合**）：详见 `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/assessment-toctou-residual-2026-09-23.md`。① 竞态类残余维持 Story 46.1 决策（descriptor-relative 仅 POSIX 可用、仍非边界；Windows 无 `O_NOFOLLOW` 回退窗口更宽）；② **新查出一处非竞态缺口**：`manifest.lock` 只钉 entry（`SKILL.md`）的 `source_hash`，而 `_materialize` 用 `shutil.copytree` 复制整棵包树（`references`/`templates`/`assets`/`scripts`），且运行期**从不读** lock ⇒ 包资源内容无完整性凭据、读取路径（`SkillPackage._read_text` → `open_text_under_root`）不校验；同类先例已在隔壁一层存在（`_bmad/render/*/manifest.json` + `render_skill.py::_verify_existing` 的逐文件哈希校验，仅重渲染时触发）。③ 建议方向 = 内容哈希钉 + 读时校验（跨平台、无新依赖、fail-loud，复用既有凭据形态），但会改变「手工编辑 lock/rendered 包后仍可读」的语义，**命中 Story 46.1 的 Ask First（导入物化/读取语义）**，故实施待授权；④ 本仓库当前未激活 importer 通道（`.heagent/skills/manifest.lock` 不存在），故该缺口暂属休眠暴露面。
  Progress（2026-09-23 同日实施，用户决策 = (a) 确认行为变化 / (b) 复用既有 `manifest.json`）：**非竞态缺口已闭合** —— `SkillPackage` 读时对渲染器 `manifest.json` 的 `outputs` 做逐资源校验，漂移即 `SkillPackageResourceError("content hash differs from manifest.json")`；底层新增原始字节摘要通道（`read_bytes_under_root` / `read_text_with_digest_under_root`，CRLF 文件亦可校验）；17 例测试（含改写/截断/entry/CRLF/未托管/凭据不可用/凭据探测次数/契约护栏），负向验证：拿掉校验调用 → 3 例漂移检测必红；凭据读取经 `is_file()` 门控（未托管包零额外 open——无门控会打破 `test_skill_packages_toctou.py` 的两条刻画测试，**该回归只在 Linux 暴露**，由 WSL 等价验证在 2256 passed 的跑法下抓出）。**竞态残余保持开启**：中间目录替换在 POSIX/Windows 上都未闭合（descriptor-relative 仅 POSIX 且仍是收窄），唯一真边界仍是 OS 级沙箱。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「MCP server / cron 子进程接入沙箱」）
  summary: MCP stdio server 子进程未接入沙箱后端：MCP server 由 SDK 自行 spawn，不经过 `ToolExecutor.execute_in_sandbox`，因此 Firejail/WinJob 对它零覆盖（无 FS 隔离、无 `--net=none`）。触发条件：连接任意 `.mcp.json` 声明的 stdio server（第三方不可信代码）；严重度：中-高；冻结边界：不得为接沙箱而改变 MCP 连接/握手契约，且即便接入仍非安全边界（须整体 OS 级沙箱兜底）。注：「cron 子进程」一半不成立——`cron/` 无子进程路径。
  evidence: `src/heagent/tools/mcp/client.py` `default_transport_opener`（Phase 4 C2 后的 stdio 分派单点）`StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)` → SDK 在 `mcp/client/stdio/__init__.py` 直接 `anyio.open_process`；其 `env` 亦不经 `scrub_sensitive_env`；沙箱侧只把 `shell` 纳入授权范围（`engine/container.default` 的 `policy.sandbox_tools`）。
  Progress（2026-09-22 复核）：Phase 4 未改变该缺口（冻结边界：不为接沙箱改连接/握手契约）；事件契约 v2 的失败分类（`error_kind`）已让 stdio server 失败可观测。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: cli.py 与 cli_goal.py 职责混杂可再拆（斜杠 handler / 装配 / replay+init；goal/ 子包已有 document.py 拆分先例（原 questionnaire.py 已随 2026-09-19 问卷删除））。触发条件：再改这两个文件的重复区；严重度：低（可用，可维护性项）；冻结边界：拆分只挪代码不改行为，wiring.py 先例（docstring 记录拆分理由）。
  evidence: `src/heagent/cli.py`（6+ 类职责）、`src/heagent/cli_goal.py`（_goal_runner noqa C901）、`src/heagent/wiring.py:1-6`（拆分先例 docstring）。
  Progress（2026-09-22 复核，保守拆分已落地，条目保持活动；当前行数：cli.py **1163**、cli_goal.py 1150+→988→**680**（2026-09-21 Phase 3：确定性内核迁 `goal/application.py`，cli_goal 收缩为渲染薄壳；2026-09-22 Phase 5 增 `emit` 发射器 ~20 行））：① cli.py init 块（模板 ×2 + `_init_project_context` + `init_cmd`，约 130 行）已拆至 `cli_init.py`（独立 click 命令 + `main.add_command` 注册，cli.py re-export 保 import 缝）；② cli_goal.py 的 GOAL.md 文档与命名层（常量块 + 9 个文档函数，约 150 行）已拆至 `goal/document.py`（cli_goal re-export，测试零改动）。**剩余**：装配块与斜杠 handler 仍留原处——大量测试 monkeypatch `heagent.cli._run_prompt` / `cli.sys` / `cli_goal._goal_session` 等**模块路径缝**（目标函数及其调用方必须同模块），且有钉死测试锁「cli 只留三个自用 goal 符号」；进一步拆分需同步迁移测试缝，收益低于风险，暂缓。

- source_spec: `_bmad-output/implementation-artifacts/arch-optimization-cycle/phase5-observability-benchmarks-docs.md`（V-系列排除项 + C3 文档收口结论）
  summary: **GUI 原生事件渲染**：GUI 观测仍走 stderr 转发（行为冻结，`gui/screens/chat.py` 自述「文案冻结」）；事件契约 v2（`RunEvent.duration_ms`/`error_kind` 顶层字段 + workflow_step_* kind）已为此铺路——GUI EventLog 可直接读事件渲染耗时/失败分类/步骤轨迹，不再受 CLI 文案约束。触发条件：GUI 观测升级需求；严重度：低-中；冻结边界：EngineEvent 模型与 GUI 既有消费面不破坏。
  evidence: `src/heagent/events/protocol.py`（v2 字段）、`src/heagent/gui/observers.py`（读 EngineEvent）、`gui/bridge.py`（StreamEvent 通道）；Phase 3 spec「不把 GUI 的 stderr 转发升级为原生渲染」排除项。

- source_spec: `_bmad-output/implementation-artifacts/arch-optimization-cycle/phase5-observability-benchmarks-docs.md`（Change Log ② + C1 测试注释）
  summary: **观测粒度残余**：① `AgentLoop._on_run_failed` façade 包装路径的 `run_failed` 事件恒 `duration_ms=0`（未计时；真实路径 `execute_run`/`stream_run` 已带全程耗时）；② workflow story batch（`max_parallel_stories>1`）路径事件为**整批一条** started/completed，非逐 story。触发条件：消费方（GUI/replay 分析）需要该粒度时；严重度：低；冻结边界：不加字段不改既有事件语义，仅补测量与发射。
  evidence: `src/heagent/agent/loop.py:_on_run_failed`（未透传 duration）；`engine/workflow_runner.py:_run_story_batch`（批内 gather 不逐 story emit）。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」）
  summary: 路径级审批分级（**条件性条目，前置未发生**）：当前审批粒度是工具级（destructive → 审批），file 工具一律被限制在 workspace 内，所以「按路径分级审批」暂无触发场景。触发条件：引入「非 workspace 的受控写场景」（例如经审批向 workspace 外写）；严重度：低（前置未发生）；冻结边界：分级只能是 `PolicyEngine` 的 defense-in-depth 标记，不得表述为 OS 级边界，也不得放松 workspace 围栏默认值。
  evidence: `src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file 工具 handler 共用同一算法）；`src/heagent/engine/policy.py`（destructive 注解闸门）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。

- source_spec: `_bmad-output/epics/epic-48-TCP网络接口周期/retrospective-epic-48.md`（同记于 `docs/frame.md` 五）
  summary: **TCP 入口不写 rollout**：`EVENTS_ROLLOUT_ENABLED` 对 `heagent tcp-server` 是**死开关**——`JsonlSink` 唯一构造点在 `cli._build_event_sink`，网络入口不订阅 sink，故开关开启也不产生 `.heagent/runs/<run_id>/rollout.jsonl`。触发条件：需要回放/审计 TCP 入口的 run；严重度：低；冻结边界：接入不得让 TCP 输入改变服务端配置（`tcp_*` 唯一读取点保持 `cli_tcp.build_server_config`），且仍非安全边界。
  evidence: 48-5 评审 W-2 实测（`tests/test_tcp_agent_integration.py` 已把「不写 rollout」钉为现状）；`docs/frame.md` 五「TCP 入口不写 rollout」行。
  Progress（2026-09-23 复核，**保持未闭合**）：接入前须先定并发语义——`JsonlSink` 的 `seq`/`_last_run_id` 是 sink 全局的，而 TCP 入口共享一个 `EngineContainer`/`EventBus` 并发服务多请求：单共享 sink 会让多 run 的 seq 交错、`assistant_message` 归属错误；每请求一 sink 则互相收到对方的全部事件（`EventBus` 无 `unsubscribe`）。修法二选一：sink 加 run 维度过滤，或 `EventBus.unsubscribe` + 每请求复用一个带过滤的 sink。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md`（§6「并发口径」+ §15 D9；对偶义务见 50-7 T10⑨）
  summary: **跨项目并发无全局上限（Epic 50 D9 采纳后的已知缺口）**：D9 裁定采纳「并发随项目数线性增长」——在途运行上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认项目上限 32 × 1 ⇒ **最多 32 个并发 run**），跨项目不共享名额、不做全局调度；而 `HTTP_MAX_CONNECTIONS`（默认 16，由 Uvicorn `limit_concurrency` 承担）**不随项目数放大**。触发条件：登记接近上限的项目数、并对多个项目同时发起运行；严重度：低-中（资源占用线性上升——每项目一套 `EngineContainer` / 事件缓冲 512 / run 历史 64 / SSE 订阅，外加真实 LLM 并发、沙箱进程与磁盘写入；且连接层可能先于运行层成为瓶颈）；冻结边界：不得为此改回「跨项目共享在途名额」（D9 已裁定为**有意语义**），也不得改每项目内部的单运行约束与会话在途保护；若要引入上限，只允许**新增**全局限流键（如 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT`），不得复用或改写既有 `HTTP_MAX_INFLIGHT_RUNS` 的 per-service 语义。
  evidence: `ARCHITECTURE-SPINE.md` §6（并发口径：32 × 1 的乘数关系 + 已知缺口声明）；`src/heagent/network/http_server.py:150`（`max_inflight_runs` 是 **service 级**字段）、`:386`（`len(self._active) >= self.config.max_inflight_runs` 按 service 判定）；Epic 49 遗留的连接层口径（`HTTP_MAX_CONNECTIONS` 与 SSE 订阅上限复用、由 Uvicorn 在 ASGI 之前拒绝，见 `docs/frame.md` 五）；本周期内对偶义务：50-2 T4（项目数上限 32 即并发乘数，改它等于改整体资源上限）、50-3 T9（须正面断言「A 项目在跑时 B 可起跑」**且**「同项目第二个 run 仍被拒」）、50-7 T10⑨（文档须写明口径与缺口）。
  Progress（2026-09-24 登记，**计划期条目**）：Epic 50 **尚未实现**（7 条 story 均 `ready-for-dev`，建集 commit `5878e92`），故本条是对**已裁定设计**的缺口登记，**不代表当前代码存在该问题**；50-7 落地时须在 `docs/frame.md` 五 增对应行，并把本条目迁移到该 Epic 的收口归档。

- source_spec: 2026-09-24 Epic 50 收口评审（三镜头）· 运行时归因与兜底族
  summary: **HTTP 运行时的三处归因/兜底薄弱点（同一族）**：① 看门狗的 `deadline_reason` 一经写入便永久保留，`_execute` 仅凭「非 None 且未在关停」判定「是超时杀的」⇒ 若 executor 吞掉第一次取消并继续跑，**之后**用户的 `DELETE` 会被记成 `timed_out` 并吞掉取消（`reopen()` 还能把 `_closing` 清回 False，理论上让旧任务上报 `timed_out`）；② `tools_in_flight` 只由 `tool_call`/`tool_result` 增减、永不衰减 ⇒ 一个**永不返回**的工具会让「静默上限」判据恒不成立，该项目的在途名额被无界占用（`HTTP_REQUEST_TIMEOUT` 默认 0）；③ SSE 订阅者上限是「先查后加」（检查在端点、登记在生成器首个 `__anext__`）⇒ 并发 `GET .../events` 可穿过限额，每个订阅者驻留一个 512 事件队列。触发条件：吞取消的 executor / 卡死的工具 / 并发订阅；严重度：中（不崩、名额最终仍可人工回收，但会静默错归因或放大内存）；冻结边界：不得改变「首位获胜」的终态语义与每项目单运行约束；①②的修法是「取消来源令牌（消费一次）」与「在途工具计龄」，③需在单次事件循环内把检查与登记合到同一步。
  evidence: `src/heagent/network/http_server.py:659`（静默判据含 `tools_in_flight == 0`）、`:665`（`record.deadline_reason = ...` 后 `task.cancel()`）、`:690`/`:710`（`deadline_reason is not None and not self._closing`）、`:780`（`record.subscribers.add(queue)`）、`:1238`（端点的先查后加）；探针证据见评审报告「镜头一④⑤ / 镜头二①②」（含实际行号与代码引用）。
  Progress（2026-09-24 登记，**未修**）：三处均**在本 Epic 增量内引入或触碰**（看门狗=commit `4f67397`），但修复后都需要新的时序测试（吞取消的 executor / 卡死工具 / 并发订阅），本次评审范围内未做——如实登记而非假装修好。

- source_spec: 2026-09-24 Epic 50 收口评审（三镜头）· 控制台阻塞 I/O 与会话列表成本
  summary: **控制台端点在唯一事件循环里做同步 I/O**：`list_sessions`（逐文件全量读 + 无 title 时全量校验）、`build_config_report`（实测中位 14 ms）、`registry.list()`（每请求每条一次 `Path.is_dir()`）、`registry.touch()`（跨进程文件锁 + 原子写）都是 `async def` 体内的阻塞调用，会卡住在途 SSE 流与其余请求；且 >1 MiB 的会话仍在列表时被整份读入（`count_messages` 只跳过计数，与 `SessionMetadata` docstring 的「避免列表时校验整份历史」不符）。触发条件：会话数/体积增长、面板被频繁刷新；严重度：低-中（单用户本机场景下不致命，属可伸缩性债务）；冻结边界：不得为此改变会话文件格式或列表接口的有界口径（D6 的「列表可退化」语义保留）。
  evidence: `src/heagent/cli_http.py:499`（`runtime.sessions.list_metadata()`）、`:595`（`build_config_report`）、`:600`（`_project_entry` 每请求遍历）、`:651`（`registry.touch`）；`src/heagent/context/session.py:388`（`read_text` 无视 `info.st_size`）、`:401`。
  Progress（2026-09-24 登记，**未修**）：修法是把这些调用挪进 `asyncio.to_thread` 或按指纹缓存；本次未做（评审只做最小修复）。

- source_spec: 2026-09-24 Epic 50 收口评审（三镜头）· 非回环运行姿态（**intent_gap，待裁决**）
  summary: **两条相关的主张冲突，需要人裁决**：① 回环闸门只装在「登记 / 移除项目」，而**危害更大的** `POST /api/projects/{id}/runs`（可跑 shell / 文件工具）、会话增删改都没有闸门——脊柱 §9 的「写通道额外要求本机回环来源」说的是配置写通道（50-5），而 49 的 `/api/runs` 本来也无闸门，故**暴露面未因本 Epic 扩大**；② 更该关注的是 `enable_cron=False` 只拒了调度器：`cron_store` 仍被绑进 loop（`cron_enabled` 默认 True）⇒ 网页运行**可以成功写入** `<项目>/.heagent/cron/jobs.json`，任务在本进程 IDLE 永不触发，却会在**后续 CLI 会话**里无人监督地执行——与 `cli_http.new_loop` docstring 自称「把带无人监督执行面的运行时装进 HTTP 进程是明令禁止的形态，绝不静默忽略」直接冲突。触发条件：把服务绑到非回环地址 + 任意客户端；严重度：中（非回环姿态）／中-高（cron 任务跨会话后置执行）；冻结边界：不得把这些闸门表述为安全边界（网页入口无认证无 TLS，须 OS 级沙箱兜底）；不得为「更安全」而破坏既有端点契约。
  evidence: `src/heagent/network/http_server.py:1320`（register 有 `_loopback_error`）vs `:1332`/`:1400`/`:1420`/`:1433`/`:1447`（rename / create_session / rename_session / delete_session / create_project_run 均无）；`src/heagent/cli.py:226`（`cron_store = JobStore(...) if config.cron_enabled else None`）+ `:275`（传给 loop）+ `src/heagent/agent/loop.py:686`（`stack.enter_context(bind_cron_tools(self.cron_store))`）；`src/heagent/cli_http.py:292-310`（`enable_cron=False` 与不可达的 scheduler 守卫）。
  Progress（2026-09-24 登记，**blocked 待人裁决**）：① 属「设计姿态」选择（49 已如此），② 的修法有两条互斥路径——「网页运行一律不绑 cron 工具（连写都不允许）」或「允许写但明确标注任务不执行」；两条都改变可观察行为，非评审可单方决定，故按契约标 `blocked` 交人裁决，未擅自改。

- source_spec: 2026-09-24 Story 50-6 实现（网页控制台 UI）
  summary: **浏览器级 UI 验收不在 CI、也不含真实 LLM 运行**：`tests/js/console_acceptance.mjs` 需要真实 Chrome/Edge（CDP）+ `heagent[http]`，而 CI 只装 `.[dev]`（`pyproject.toml` 里 `http` 与 `dev` 分离）⇒ 它只能手动跑，story 50-6 的验收清单正是由它产出的；同时该次验收**没有**跑「真实模型 → SSE → 对话区流式渲染」这条链（本机无可用 provider，Ollama 未运行），该链的前端侧由 node 探针（`tests/js/app_probe.js` 用例 A/B/C/D/E/N）与 Epic 49 的服务端用例覆盖。触发条件：改 `app.js`/`index.html`/`styles.css` 后要确认「真浏览器里也没坏」；严重度：低（改动有探针兜底，但探针是 DOM 替身——CSP 是否被违反、有没有第三方请求、窄屏计算样式只有真浏览器能证明）；冻结边界：不得为让浏览器验收进 CI 而给 dev 依赖加 playwright/puppeteer（保持零构建链与「GUI / 浏览器不进 CI」的既有立场），也不得把 `console_acceptance.mjs` 的一次通过当作「UI 无回归」的充分证据。**2026-09-24 实例（这条「不够充分」的最强证据）**：50-6 的 17/17 通过之后仍漏掉「首页确认遮罩吞掉真实鼠标点击」（`hidden` 属性为真而计算样式 `display:flex`）—— 因为清单只断言属性、且 `click()` 走 DOM API（绕过命中测试）；修复后清单新增 A1b（计算样式 + CDP `Input.dispatchMouseEvent` 真实点击）为 **18 行**，详见 Z-D15。
  evidence: `tests/js/console_acceptance.mjs`（自起真实 http-server + headless Chrome，CDP 驱动真实点击；17 行清单含窄屏/凭证零明文/磁盘副作用断言）；`tests/test_http_web_ui.py`（探针用例的 skipif 只要求 node，不要求浏览器）；`pyproject.toml`（可选依赖分组）。
  Progress（2026-09-24 登记，**未闭合**）：验收输出见 `_bmad-output/epics/epic-50-网页控制台周期/reviews/acceptance-50-6-console-ui.md`（17/17 PASS，Chrome 153.0.8010.48）；该报告同时给出复跑命令与依赖前提。

- source_spec: 2026-09-24 Story 50-6 实现（网页控制台 UI）· AC7 / UX-DR3
  summary: **「高影响键的差异化确认」缺后端风险标记**：UX-DR3 要求「写入被标记为高影响的键必须显式确认」，但 `ConfigItemResponse` 没有任何 per-key 风险/影响字段（`config_catalog` 的分组只表达来源与只读原因）⇒ 50-6 的实现口径是**所有写入都二次确认**（确认框列出将改的键、「只对下一次运行生效」、写入路径与备份语义），既不漏确认也不做分级。触发条件：写闸门开启 + 用户频繁改配置（每次都弹确认框 = 体验摩擦）；严重度：低（偏体验、不影响正确性，且「宁多确认」方向是安全的）；冻结边界：若要分级，只能**新增后端字段**（如 `ConfigItemResponse.impact` 或写进 `config_catalog` 的分类常量）并由服务端声明，**不得**在前端硬编码键名清单（那是第二个事实源，必然与白名单漂移）；分级仍是 defense-in-depth 提示，不改变写通道的 fail-closed 校验。
  evidence: `src/heagent/network/http_console_protocol.py`（`ConfigItemResponse` 字段集：无风险/影响字段）；`src/heagent/web/app.js::saveConfig`（写入前一律 `askConfirm`）；`src/heagent/config_catalog.py`（分类常量只产出 group / writable / reason）；探针用例 `TestConsoleSettingsPanel` 钉住确认框文案与「未确认不发请求」。
  Progress（2026-09-24 登记，**未闭合**）：该口径裁定记录在 story 50-6 的 Dev Agent Record（「与 story 文本的偏离」条）；若后续要分级，需先定影响分级的事实源。

- source_spec: 2026-09-24 Epic 50 收口评审（第二轮）· 写入通道与保真写的低危残余（`reviews/review-epic-50-closure.md`）
  summary: **四类 low 级残余**（都在写入通道 / 保真写面上，均不阻塞收口）：① **`.env.lock` 落在用户项目根** —— `persist.atomic_update_bytes` 的锁文件与目标**同目录**，故写项目 `.env` 会在**用户的项目根**留下 0 字节 `.env.lock`（评审探针实测：`['.env','.env.lock','.heagent']`）；HeAgent 自己的仓库有 `.gitignore` 条目，**用户的项目没有**。② **回滚失败时的文案不实** —— 回读不符时无条件回 `the project .env was rolled back to its previous content`，而回滚本身失败只 `logger.error`（`persist._restore_bytes`）⇒ 对直接调 API 的客户端是假话（UI 侧文案诚实：「服务端已尝试恢复备份」，且该码不在 JS 的 `DETAIL_CODES` 里、不显示服务端 message）。③ **写锁内 I/O 时长** —— `validate_candidate`（构造 `Settings` ⇒ 读候选临时文件 + 全局 `.env` + 环境）与备份目录扫描都在**跨进程锁内**完成 ⇒ 并发热点下写方可能得到 `config_write_failed`（锁超时 5s）而非 `config_conflict`（**fail-closed：无损坏、无部分写入**）。④ **无末行换行文件的追加约定** —— 追加新键沿用「文件无末行换行」这一属性（实测 `MAX_ITERATIONS=5\nSHELL_TIMEOUT=60`），是有意保真，但部分工具约定「文件必须以换行结尾」⇒ 记入备查。
  evidence: `src/heagent/persist.py::atomic_update_bytes`（`lock_path = path.with_name(path.name + ".lock")`）；`src/heagent/config_write.py::_verify` 与 `_apply_locked`（候选构造 / 备份回收在 `atomic_update_bytes` 的回调内）；`src/heagent/envfile.py::replace_or_append`（末行换行跟随文件）；探针 `.heagent/tmp/review50_probe.py` 的 B / E / K 三例实测输出；评审报告镜头一 #1/#2/#3 与镜头二 ⑤。
  Progress（2026-09-24 登记，**未修**，冻结边界）: ① 锁文件**刻意不删**（删除会引入「B 等旧 inode、C 拿新文件加锁成功」的竞态，见 `persist` 模块注释），挪到状态目录会改变锁语义 ⇒ 修法只能是「写入方提示 / 文档说明」，**不得**改锁的落点语义；② 精确文案需把回滚结果从 `persist` 回传（新增返回值或异常类型），属改造；③ 收窄需「锁外构造候选 + 锁内复检指纹」的乐观重试，属流水线结构调整。三条都超出「评审期最小修复」范围，故如实登记而非草率改动。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/stories/50-8-console-ux-refinement.md`（R2 原生目录选择，2026-09-24 实现）
  summary: **网页请求可拉起宿主 GUI 进程（有意引入的新暴露面）**：`POST /api/dialogs/pick-directory` 会在**服务端所在机器**弹出一个原生目录选择窗口（子进程 `tkinter` / `powershell`）。它带来的是便利而非权限（返回值仍要过 `POST /api/projects` 全套校验），但暴露面是实打实的：**任何能连上该端口的本机进程都能让服务机弹窗**（骚扰面），而「回环 peer」不等于可信（用户自己浏览器里的任意页面 peer 也是 `127.0.0.1`，见 frame 五同名条目）。另有三种**不可用**环境：无图形后端（容器 / 缺 `_tkinter` 的 Linux）、服务在远程机器而浏览器在别处（窗口弹在服务机，对调用者无用）、`--dialog-backend none` 显式禁用。触发条件：把服务绑到可被其它本机进程访问的端口 / 在无 GUI 环境部署；严重度：低-中（不崩、不改数据，最坏是弹窗骚扰与一次失败的登记尝试）；冻结边界：**不得**把它表述为安全边界，**不得**为「更安全」而改成服务端目录浏览 API（那会把宿主目录结构开放给回环客户端），也**不得**让它绕过 `POST /api/projects` 的任何校验（选择器不是权限来源）。
  evidence: `src/heagent/cli_dialogs.py`（后端顺序 `resolve_backend` / 冻结脚本 `_TK_SCRIPT`+`_POWERSHELL_SCRIPT` / `DirectoryPicker` 单在途 + 300s 超时 + kill + 有界回收 / 只认 ASCII 标记行 + `is_dir()` 复验）；`src/heagent/network/http_server.py::_build_dialog_endpoint`（`_loopback_error` + POST-only + 新码 `dialog_unavailable` 503 / `dialog_busy` 409）；`src/heagent/cli_http.py::HttpProjectConsole.pick_directory`（入口层持有单在途）。实测：真机探针 `.heagent/tmp/probe_50_8_dialog_real.py`（`auto → tkinter`，2s 超时后 kill + 归还名额 + WARNING）；浏览器清单 `acceptance-50-8-refinement.md` 的 A5b / B2 两行（不可用路径端到端）。
  Progress（2026-09-24 登记，**未修**，冻结边界）：本暴露面是**有意引入**并已在 `docs/frame.md` 4.18（安全声明段）与五（已知缺口）双处如实登记；三条防线（回环门 / 单在途 / 冻结 argv + 超时）都在测试与浏览器清单里有可见判据，负向验证见 `.heagent/tmp/mutate_50_8.py` 的 M1–M4。**未做**（如实记录）：没有「谁能让服务机弹窗」的更强授权（如每会话令牌），也不打算做——那属于「把非安全边界做厚」的范畴，真正的边界仍是 OS 级沙箱。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/stories/50-8-console-ux-refinement.md`（R2/R5 的验收与判据残余，2026-09-24 实现）
  summary: **两处「判据/验收」残余（不影响功能，但会在改动时静默失效）**：① **真实原生窗口无法自动化验收** —— 选中并确认需要人眼与人手，浏览器清单只能覆盖「按钮存在」「不可用路径」「取消/超时」；`tkinter` 子进程脚本在 CI 里**永不执行**（Linux 镜像可能无 `python-tk`），只钉了「能编译 + 标记行 / 标题插值唯一」；② **网页侧读取结果收敛依赖 `Error:` 前缀约定** —— 内置工具用**返回值** `Error: ...` 表达可预期失败（`is_error` 仍为 `False`），`file_read` 的失败消息因此靠 `_looks_like_a_failure()` 的字符串前缀识别；若将来把工具改成结构化错误（抛 `ToolError` / 返回带 `is_error` 的对象），该判据应退化为只看 `is_error`，否则前缀写成别的样式的失败会**静默从页面上消失**。触发条件：改动 `cli_dialogs` 的冻结脚本 / 改造内置工具的错误返回形态；严重度：低（都有测试兜底，但兜的是「现在的形态」）；冻结边界：不得为了「可自动化」而给 dev 依赖加 playwright/puppeteer（保持零构建链与「浏览器不进 CI」的既有立场），也不得把真实弹窗的一次人工通过当作「选择器无回归」的充分证据。
  evidence: `tests/js/console_acceptance.mjs` 的 A5b / A11b / A11c / B2（真实浏览器，无真实弹窗点击）；`tests/test_cli_dialogs.py::TestSpawnDiscipline::test_frozen_scripts_are_valid_python_syntax`（只 compile 不执行）；`src/heagent/cli_http.py::_looks_like_a_failure` 与 `tests/test_http_agent_api.py::test_read_tool_error_message_is_still_shown_in_web`（**明写**「内置工具返回 Error 字符串不算异常」这一约定）；浏览器清单里「真浏览器 LLM 运行」仍是既有缺口（Z-D15 同处登记）。
  Progress（2026-09-24 登记，**未修**）：两条都已在 `docs/frame.md` 五 与验收报告里如实登记；`file_read` 失败路径有专门的真实装配用例（`tool_output` 仍可见），负向验证见 `.heagent/tmp/mutate_50_8.py` 的 M10（去掉前缀判据 ⇒ 精确变红）。

---

## 闭合归档（勘察类正文 + 回填索引）

## 状态总览

**① 勘察类（正文在本文件）——10 条**

| ID | 条目 | 结论 | 闭合 commit |
|----|------|------|-------------|
| Z-D1 | memory→engine 残余反向边（dream.py） | 已闭合 | `7b1b16b` |
| Z-D2 | 六处手写 frontmatter 解析器漂移 | 已闭合（实为 6 处，台账原记 4） | `e0d05cb` |
| Z-D3 | provider 三套回退骨架收敛 | **评估结论 = 不收敛**（有意分歧被护栏测试钉死），补四点互指注释 | `beea1a2` |
| Z-D4 | JsonlSink 逐事件同步落盘 | **评估结论 = 保持现状**（replay 契约天然满足），仅 docstring 如实化 | `4b5f037` |
| Z-D5 | CronScheduler 同步 store 调用 | 已闭合（4 处 to_thread，台账漏记 1 处） | `a633c5c` |
| Z-D6 | SafetyGuard/PolicyEngine 拦截零日志 | 已闭合（_block 单点 warning + policy 分级） | `3dd1050` |
| Z-D7 | GoalWorkflowState 三死字段 | 已闭合（容错忽略兼容策略） | `4b5f037` |
| Z-D8 | `RoleSpec.sandbox_profile` 死字段 | 已闭合（取**删除**方向，非激活） | 已提交 `dfe6eef`（2026-09-18） |
| Z-D9 | 沙箱无进程数限额 + WinJob 常量误写 | 已闭合（`SANDBOX_NPROC_LIMIT` + 修正 `PROCESS_TIME=0x2`） | 已提交 `8de6c63`（2026-09-18） |
| Z-D12 | MEMORY.md 非 UTF-8 让整个 run 起不来 | 已闭合（fail-soft：跳过注入 + **点名文件**的告警；文件字节一字不动） | `b01e09c`（2026-09-23） |

**② 已按归属 epic 回填（正文在各自周期目录）——5 条**

| ID | 归属 epic | 条目 | 正文位置 |
|----|-----------|------|----------|
| Z-D10 | Epic 48（Story 48-5 评审 C-1） | 运行栈日志的观测故障免疫 | `epics/epic-48-TCP网络接口周期/deferred-work.md` |
| Z-D11 | Epic 48（Story 48-5 评审 C-2） | 日志行的凭证脱敏 | 同上 |
| Z-D13 | Epic 50（Story 50-5 实现） | 写通道可把「资源旋钮」键设成无界值 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D14 | Epic 50（Story 50-5 实现） | 审计文件无保留期 / 条数上限 | 同上 |
| Z-D15 | Epic 50（Story 50-6 实现，用户实测发现） | 首页加载即弹出关不掉的确认遮罩 | 同上 |

> `Z-Dn` 编号在**本文件**登记（跨文档引用如 `Z-D8` / `Z-D15` 仍以此为索引），但**正文只有一份**，在上表第二列指向的文件里；本文件不留副本（2026-09-24 回填）。

---

## Z-D1 memory→engine 残余反向边（dream.py）

- **来源**：2026-09-17 架构收敛批次（persist/roles 迁出 engine 包）遗留登记。
- **问题**：`memory/dream.py:47` 运行期整包导入 `heagent.engine.EngineContainer`（触发条件：engine 包级 `__init__` 将来依赖 memory 包级 `__init__`；当前无环，架构文本性违规）。
- **结论**：**已闭合**（2026-09-17，commit `7b1b16b`）。EngineContainer 移入 TYPE_CHECKING（经 `engine.container` 子模块）、构造参数 `engine` 改必传、删除 `EngineContainer.default()` 缺省回退——cli.py 与全部测试本就显式注入，零调用方受影响；FORBIDDEN_RUNTIME_IMPORTS 为 memory 补 `heagent.engine` 断言。DreamScheduler 入口层装配现状未变（冻结边界）。
- **证据**：`tests/test_dream.py` 全绿 + `tests/test_architecture_contracts.py` 新契约。

## Z-D2 六处手写 frontmatter 解析器漂移

- **来源**：2026-09-17 架构与代码优化勘察（原登记 4 处，收敛时发现实为 **6 处**——漏记 `roles.py _parse_role_md` 与 `skill_packages._parse_metadata`）。
- **问题**：各模块独立维护 `---` frontmatter 正则与键值解析，同一文档在不同模块可能解析出不同结果。
- **结论**：**已闭合**（2026-09-17，commit `e0d05cb`）。新建零 heagent 依赖顶层模块 `frontmatter.py`（persist/roles 同层）：两个分隔符变体（EOF / 须尾随换行，有意并存）+ 严档 `parse_strict_pairs` / 宽档 `parse_inline_pairs` / 标量 `parse_scalar`；六处调用方改指向共享模块，公开 API、异常类型与消息文案逐字保持；`skills._FRONTMATTER_RE` 常量名保留（就地改写字节跨度依赖）；架构契约新增「frontmatter 正则只允许出现在 frontmatter.py」断言。
- **证据**：`tests/test_frontmatter.py`（直测）+ 六个调用方既有测试全绿。

## Z-D3 provider 三套回退骨架收敛

- **来源**：2026-09-17 架构与代码优化勘察（原设想「回退模板 + sticky/reset 策略参数」收敛）。
- **问题**：chain / key_rotation / switchable（加 router 实为四套）各自维护平行 send/stream 回退循环。
- **结论**：**评估结论 = 不收敛**（2026-09-17，commit `beea1a2`）。勘察推翻收敛设想：分歧是有意设计且被护栏测试钉死——`retry.py` docstring 明言「不要合并成一套」（判据矩阵三方不同：chain 回退一切非 NON_TRANSIENT 含 AUTH_FAILED 跨 provider；key_rotation 仅 RATE_LIMITED+AUTH_FAILED；switchable/router 仅 RATE_LIMITED+TRANSIENT），索引语义各异（chain 复位 / key_rotation 成功即粘 / switchable 回退成功才粘 / router 无状态单兄弟重试），`test_retry.py::TestPoolFallbackPolicy` 钉死分歧。按冻结边界交付最低要求：switchable 与 router 的 send/stream 补齐互指注释（chain↔key_rotation 原有），形成四点互指网；行为零改动。

## Z-D4 JsonlSink 逐事件同步落盘

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：`_append` 每事件 mkdir+open+write+close，docstring 自称「只做一次 write/flush」与实际不符。
- **结论**：**评估结论 = 保持逐事件 append，不改实现**（2026-09-17，commit `4b5f037`）。close 即 flush 天然满足 replay 契约（crash 已写前缀可回放）；缓冲/常驻句柄引入句柄生命周期与丢失窗口，当前吞吐（LLM 工具循环级）下开销可忽略。仅 docstring 如实化并记录决策理由。

## Z-D5 CronScheduler 同步 store 调用

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：store 的 list/update/remove 在 async 调度路径上同步执行（同步文件 I/O + Windows 替换退避）。
- **结论**：**已闭合**（2026-09-17，commit `a633c5c`）。实为 4 处（台账漏记 one-shot 的 `remove`）：全部经 `asyncio.to_thread` 卸载（对齐 273cb89 与 WorkflowCheckpointStore 先例），JobStore 语义零改动。
- **证据**：`tests/test_cron.py::TestCronSchedulerTickPath`（tick 路径集成测试 ×2；两测试用不同 job_id——ledger key 含分钟级时间戳且共享默认 ledger 路径，同分钟重复 id 会被幂等 lease 跳过）。

## Z-D6 SafetyGuard/PolicyEngine 拦截零日志

- **来源**：2026-09-17 架构与代码优化勘察（台账原记「48/108 文件无 logger」，实测已 61/108）。
- **问题**：拦截只抛异常 + 发事件，日志零轨迹，事后无法审计。
- **结论**：**已闭合**（2026-09-17，commit `3dd1050`）。`safety.py` `_block()` 单点收口落 warning（覆盖全部 5 个拦截分支）；`policy.py` 5 处 BLOCKED 落 warning、APPROVAL_REQUIRED 落 info（SANDBOX_REQUIRED 常规路由不记防刷屏）；拦截语义零改动。
- **证据**：`tests/test_safety.py` / `tests/test_engine_p0.py` 各补 caplog 断言。

## Z-D7 GoalWorkflowState 三死字段

- **来源**：2026-09-17 架构与代码优化勘察（读者已随 RecoveryEnvelope 删除）。
- **问题**：`segment_index` / `segment_tokens` / `cumulative_tokens` 三字段无人读，仅落盘 schema 保留。
- **结论**：**已闭合**（2026-09-17，commit `4b5f037`，兼容策略 = 容错忽略）。三字段删除；pydantic 默认 `extra='ignore'` 保证旧 workflow.json 仍可加载；`test_engine_workflow.py` 新增含三键旧文件的加载测试固化契约。

## Z-D8 `RoleSpec.sandbox_profile` 死字段

- **来源**：2026-09-17 沙箱硬化勘察（第二轮优化批次）；2026-09-18 处置。
- **问题**：字段**既无消费方也无写入方**——全仓检索仅 `roles.py` 字段定义与 `sandbox.py` 一句 docstring；`_parse_role_md` 的 `keys=("name", "description", "tools", "max_iterations")` 从未解析它，故连从角色 `.md` 都设不了；`SubAgent._build_engine` 克隆父 policy 时不读该字段。
- **结论**：**已闭合**（2026-09-18，取「**删除**」方向而非「激活」）。① 删除 `roles.py` 字段与其注释；② 改写 `tools/sandbox.py:260` docstring——profile 的真正入口是 `PolicyEngine` 裁决出的 profile 名（`SANDBOX_PROFILES` / `SANDBOX_TOOL_PROFILES`，2026-09-17 硬化批），不再谎称来自角色字段；③ 修正 `docs/frame.md` 4.4 里「使 `RoleSpec.sandbox_profile` 死字段激活」这句**从未成立**的旧表述。**未选激活**的理由：谓词为「角色声明了 profile 但沙箱未授权」时必须 fail-safe 阻断（冻结边界），于是该字段只剩「沙箱已强制时换参数集」这点表达力，低于维护成本（YAGNI）。
- **证据**：`tests/test_roles.py` / `tests/test_architecture_contracts.py` / `tests/test_sandbox*.py` 全绿；`docs/frame.md` 4.4 与本文件引用同步。

## Z-D9 沙箱无进程数限额 + WinJob 常量误写

- **来源**：2026-09-17 沙箱硬化勘察（兑现资源限额 Resolution「进程数限额另立条目」）；2026-09-18 处置。
- **问题**：① 沙箱 shell 无**进程数**上界——firejail 未映射 `--rlimit-nproc`，WinJob 的 `ActiveProcessLimit` 字段虽已内联定义却从未赋值；fork bomb 只被 `tools/safety.py` 黑名单正则启发式覆盖（非资源上界）。② **顺带查出的既有 bug**：`WinJobBackend.run()` 把 `JOB_OBJECT_LIMIT_PROCESS_TIME` 误写为 `0x00000008`——按 Windows SDK（winnt.h）该位是 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`，`PROCESS_TIME` 的正确值是 `0x00000002`。后果：配了 `SANDBOX_CPU_SECONDS` 时置位的是 ACTIVE_PROCESS 而 `ActiveProcessLimit` 仍为 0——**CPU 时间限额完全不生效，反而施加了「活动进程上限 0」**。
- **结论**：**已闭合**（2026-09-18，取「补齐」方向）。① 新增 `Settings.sandbox_nproc_limit`（`SANDBOX_NPROC_LIMIT`，默认 0=关闭），经 `container.default()` 同时透传两个后端；② `FirejailBackend._build_argv` 在 `--rlimit-cpu` 之后注入 `--rlimit-nproc`（0 时零参数，默认 argv 逐字节不变）；③ `WinJobBackend.run()` 置 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`；④ 修正 ②的常量误写（`PROCESS_TIME = 0x2`）。触发行为与内存/CPU 限额一致：**显性失败**（子进程被终止 → 非零退出码），不静默。⚠ **两个后端语义不对称（如实标注，不掩盖）**：firejail 的 `--rlimit-nproc` 底层是 `setrlimit(RLIMIT_NPROC)`，Linux 按**真实 UID** 计数（非 cgroup/job 作用域），设小了会波及同一用户的其他进程；WinJob 的 `ActiveProcessLimit` 才是 job 作用域——故默认关闭。
- **证据**：`tests/test_sandbox_mode.py`（默认值 / 两后端装配 / argv 注入与零参数三条）、`tests/test_coverage_sandbox.py::test_run_applies_resource_limits`（0x2 与 0x8 分开断言，钉死常量区分）；`docs/frame.md` 4.4 与配置表、`.env.example` 同步。

## Z-D12 MEMORY.md 非 UTF-8 让整个 run 起不来

- **来源**：2026-09-23 代码评审（commit `7b95e56`，`<memory>` 注入字节预算）。**本节 2026-09-24 由活动区同名条目的副本改写而成**——此前状态总览表已有 Z-D12 行、正文却缺该小节。
- **问题**：`FactStore._load_facts` 以 `read_text(encoding="utf-8")` 读取，文件若被非 UTF-8 编辑器（如 GBK）保存即抛 `UnicodeDecodeError`；`_memory_block` 不捕获 ⇒ 异常经 `build_system_prompt` 逃到 `run_lifecycle` 的新 run 初始化，该 run 直接失败。触发条件：用户手工编辑 `.heagent/memory/MEMORY.md` 并以非 UTF-8 保存；严重度：低（记忆是非关键资产，却造成硬失败）；冻结边界：加载失败必须 fail-loud **且错误可定位到该文件**，但不得吞掉内容或改写文件本体（与「超预算绝不静默」同立场）。
- **结论**：**已闭合**（2026-09-23，**用户裁定 = fail-soft**）。`_load_facts` 捕获 `UnicodeDecodeError` → WARNING（**点名该文件**）+ 返回空列表 ⇒ `<memory>` 块不注入、run 照常完成；文件字节一字不动（只降级注入、不改写内容）。**冻结边界更新**：原「必须 fail-loud」改为「注入路径 fail-soft + 可定位告警；写路径（`fact_add` → `FactStore.add`）的同类失败已由 `ToolExecutor` 的 catch-all 兜成 `is_error=True` 的工具错误、不中断循环」——两条路径都不得吞掉或改写文件内容。
- **证据**：探针 `.heagent/tmp/gbk_probe.py` 实测 `RAISED UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd6 in position 2`；改动 = `src/heagent/memory/facts.py`（+19/−2）+ 4 例测试（`tests/test_memory.py::TestFactStoreNonUtf8File` 3 例 + `tests/test_agent_loop.py::TestAgentLoop::test_run_survives_undecodable_memory_file` run 级端到端），commit `b01e09c`；`src/heagent/agent/run_lifecycle.py`（`asyncio.to_thread(loop._build_system, …)` 无捕获）。负向验证：回退该守卫（HEAD 版 `facts.py`）+ 新 4 例 → **4 failed**，run 级用例的 traceback 正是本条目声称的链路（`run_lifecycle.init_new_run` → `_build_system` → `build_system_prompt` → `_memory_block` → `read_text`）；全量 `pytest -q` 2530 passed。**非本次改动引入**（改动前同样直调 `facts.load()`），故按 defer 记录。
- **同域后续（非本条范围，仅备查指针）**：`95fe8f6` 修「MEMORY.md 带 UTF-8 BOM 时首条事实被静默丢弃」（新增 `_strip_bom`，读路径与写路径统一剥离、写回归一化为 UTF-8 无 BOM）；`1b8aa8f` 单点修 frontmatter 层同类 BOM（两个分隔符变体的正则容忍文件头 BOM，skills/slash/roles/artifacts/goal/skill_packages/workflow 一次覆盖）；两者均**未另立台账条目**（2026-09-23 用户裁定）。
