# HeAgent 全周期综合回顾

> 生成: 2026-07-22；最近一次整理: 2026-09-26。本文是历史回顾与跨周期教训；活动 deferred 正文现以根目录 `open-items.md`（2026-11-15 由 consolidated-overview.md 与 implementation-artifacts/open-items.md 合并定名）「活动（未闭合）条目」节为准。
> 覆盖: Epic 1–57 + S1–S4，**26 个周期**（**61 个 Epic 条目** = Epic 1–57 + S1–S4；另含架构优化周期 Phase 0–5，非 BMad 流程；2026-10-27 刷新）
> 基准: **3765 passed / 50 skipped / 28 deselected**（2026-10-23 实测）、ruff / mypy clean、覆盖率 **92.47%**（gate 87）
>
> 归档更新：2026-09-14 已完成实现 spec 按 Epic 40 / Epic 47 归档；2026-09-15 `patches/` 目录解散（补丁 spec 按归属 epic 归档）、跨周期 deferred 台账按 epic 归并。
> **口径说明**：早期章节是正式回顾，后续章节包含补录速览；未完成正式回顾的周期会明确标注 `optional`。Epic 48 / 50 有正式回顾；Epic 49 依据交付记录与评审产物摘录，状态以 `sprint-status.yaml` 为准。

---

## 一、各周期要点速览

### 1. 主线 MVP（Epic 1–5）· 2026-05–06

| 维度 | 要点 |
|------|------|
| 成就 | BaseProvider Protocol 双实现 (OpenAI/Anthropic)、ProviderChain+KeyRotation 多层容错、@tool 声明式注册、AgentLoop 主循环、SafetyGuard、并行工具执行、会话持久化+上下文压缩、自学习记忆三件套 (skills/facts/profile)、多 Agent 并行编排 |
| 难点 | 双层异常重包、流式 backstop 不对称、P0.2 compressor 超窗口、SubAgent 竞态误判（经核实「不成立」） |
| 做对 | 协议优于实现 (Protocol+decorator)、deferred 编号化跟踪、「不成立」关闭+回归测试锁定、依赖最小化 |
| 改进 | 安全边界诚实度、send/stream 对称测试、并发竞态先核实 await 交错再定级 |

### 1b. 自学习闭环（Epic 6–10）· 2026-06

> 2026-09-20 补录速览（此前遗漏；规划拆分见 `epics/epic-01-10-主线规划周期/epics-self-learning.md`）。

| 维度 | 要点 |
|------|------|
| 交付 | Epic 6 Context Files 自动加载（FR-20）、Epic 7 SOUL.md 人格系统（FR-21）、Epic 8 Memory Nudge 记忆提醒（FR-22）、Epic 9 Skill Curator 技能策展（FR-23）、Epic 10 Cron 定时调度（FR-24）——主线 FR-20~24 全部交付，sprint-status 全 `done` |
| 形态 | 仅 Epic 1/2/4/5/10 建有 story 子目录，Epic 6-9 无独立 story 文件（规划粒度到 epic 级） |

### 2. MCP Client 集成一（Epic 11–13）· 2026-06–07

| 维度 | 要点 |
|------|------|
| 成就 | 零侵入集成 (AgentLoop+ToolRegistry API 零改动)、双 transport 统一 (stdio+HTTP)、协议演进封装、错误隔离坚固、GitHub E2E 只读验收、安全立场诚实声明 |
| 难点 | eager vs lazy 发现、生命周期不污染 AgentLoop、安全诚实 vs 实用张力、MCP SDK 版本锁定 |
| 做对 | 架构基于真实代码核实非臆断、YAGNI 克制 (不抽 Protocol/不新建异常/不新建重试)、deferred 编号化、安全声明同构 |
| 改进 | FR-3 断连 auto-unregister (已补)、MCP 输出围栏 V1 缺位 (已补 DP-4)、回顾非实时 (应在 epic 完成后即做) |

### 3. MCP V2 + 内置工具扩展（Epic 15–18）· 2026-07（story 归档沿用旧编号 14–17，+1 偏移对照见该周期 README）

| 维度 | 要点 |
|------|------|
| 成就 | 写操作治理确定性闸门 (annotations→审批/放行/fail-safe)、Resources on-demand 桥接、Prompts slash 命令、4 个 git 内置工具、v1→v2 隔离层先行 |
| 难点 | fail-safe 精准作用域 (仅 MCP+缺注解)、annotations 不可信但又用它裁决的张力、两份 Epic 14 编号冲突、跨 server 同名 URI 消歧 |
| 做对 | 步 0 前置闸门 `schema=None` 零回归保护、显式策略优先于 annotations、`guard_content` 提取为公共函数、Resources on-demand / Prompts user-controlled 正确切分、MCP 后续不作为必要功能——边界清晰 |
| 改进 | Epic C (Prompts) 预算紧张仍交付——应先验证 A+B、`idempotentHint`/`openWorldHint` 透传不裁决但 LLM 可见、Prompts slash 分发器最简实现 (未来可能需要结构化注册表)、git 工具本质是 shell wrapper |

### 4. Sandbox 硬化（Epic S1–S4）· 2026-07-20

| 维度 | 要点 |
|------|------|
| 成就 | profile → firejail 参数映射、零门槛可及 (.env/CLI 启用)、Linux 进程组 kill + `--private` workspace 隔离、contextvar 同构注入 |
| 难点 | 纯函数可测性 vs 运行时 contextvar、降级不抛异常意味着静默失去保护、`--private` 参数插入位序 |
| 做对 | 每个 FR 至少 1 独立单测+1 集成测试、模块边界严格 (不反依赖 agent/providers/memory)、`available` 属性暴露可观测性、安全声明始终诚实 |
| 改进 | S4-1 emit 事件被跳过 (可观测性缺口)、降级为静默 (伪安全感)、无内置安全 profile 库、无人验证 profile 参数合法性 |
| 更正 (2026-09-18) | 原记「死字段激活 (`sandbox_profile` → firejail 参数映射)」**不准确**：`RoleSpec.sandbox_profile` 从未被任何代码读取，profile 的真正入口是 2026-09-17 的 `SANDBOX_PROFILES` / `SANDBOX_TOOL_PROFILES` 配置；该死字段已于 2026-09-18 删除 |

### 5. 健壮性与质量硬化（Epic 19–20）· 2026-07-21

| 维度 | 要点 |
|------|------|
| 成就 | 跨进程文件锁 (POSIX/Windows 自适应)、Cron 范围/步进表达式、WinJobBackend (Job Objects)、覆盖率 89→90%、CI 3 平台×3 Python 矩阵、静态分析 (Ruff/Bandit/pip-audit)、v0.3.0 版本同步 |
| 难点 | 跨平台文件锁双实现、Cron 范围+步进组合解析、Windows Job Objects (ctypes)、覆盖率 90% 硬拦精准定位 |
| 做对 | 「不改架构、不加依赖、全 stdlib」、优雅降级模式一致、defense-in-depth 意识贯穿、参数化对齐测试、CI 不引入提交延迟 |
| 改进 | agent/loop.py 复杂度是技术债 (C901 accepted)、覆盖率 438 条 miss 可推 92%、benchmark 缺乏历史趋势追踪 |

### 6. 质量工程深化（Epic 21–24）· 2026-07-22

| 维度 | 要点 |
|------|------|
| 成就 | Coverage 工程化 (`[tool.coverage]` 段落入)、benchmark 重构 (pytest-benchmark) + CI 历史对比、Docker 硬化 (.dockerignore/HEALTHCHECK/digest)、CI 效能 (pip 缓存/3.14-dev)、安全左移 (CodeQL/dependency-review)、pre-commit 加固 (卫生 hooks+bandit)、Ruff 规则扩展 (PLC/RUF/PT/PIE+format) |
| 难点 | benchmark 语义迁移 (单次→多轮)、CI runner 噪音 (20% 退化阈值)、新增 ruff 规则告警量控制、HEALTHCHECK 无 HTTP 端点 |
| 做对 | benchmark warning 不 fail (AD-2)、3.14-dev continue-on-error (AD-4)、CodeQL 仅 security+每周 (AD-3)、分层门禁 (本地 88/CI 90)、豁免必须注释、历史 artifact 下载失败优雅跳过 |
| 改进 | coverage fail_under 未提升 (AD-7)、CodeQL 仅 security (quality 可能藏 bug)、bandit -ll 可探讨 -l、benchmark 数据不入库 (artifact 7 天过期)、Docker digest 无自动更新 |

### 7. GUI 终端界面（Epic 25–28）· 2026-07-23

| 维度 | 要点 |
|------|------|
| 成就 | Textual TUI 四阶段 12 stories 全部 done（流式聊天 / 工具可视化 + 斜杠命令 / 管理面板 / 可观测性，FR-G1~G24） |
| 难点 | 异步事件与 Textual 事件循环桥接、工具卡片状态机、run 树（supervisor → sub-agent）可视化与 resume |
| 做对 | `AgentBridge` 持有并观察 `AgentLoop`（核心零改动）；`gui` 作可选依赖（textual）+ 懒加载 `heagent gui` |
| 改进 | **（2026-09-18 复核）** GUI 测试自 2026-09-14 起（`tests/test_gui_tool_state.py`）、2026-09-17 增 `tests/test_gui_goal.py`；retrospective **仍为 `optional`** |

### 8. 交互与可扩展层（Epic 29–35）· 2026-08-19

| 维度 | 要点 |
|------|------|
| 成就 | 运行时审批闭环（`engine/approval.py`：`APPROVAL_REQUIRED` 从「死判决」变可交互授权）、会话恢复（`--continue` / `--resume`）、斜杠命令注册表 + 用户自定义命令、Hooks、Plan Mode、配置驱动角色 + 成本估算、CLI 收尾；7 Epic / 27 story 项 |
| 难点 | 审批的 run 粒度授权与幂等（授权写 `RunContext.metadata["approved_tools"]` 后重新裁决）、Plan Mode 排除不可信 MCP `readOnlyHint`、Hook 阻断语义只能显式 await |
| 做对 | 全部经扩展点注入（`ApprovalHandler` / `hooks.json` / `commands/*.md` / `agents/*.md`），`AgentLoop` 与工具链零改动；安全立场一律标注 defense-in-depth 非真边界 |
| 改进 | **（2026-09-18 复核）** sprint-status 顺序已修正；GUI 侧 `/goal` 输出与取消已接入（E41-D7，`44ab001`）；**GUI 侧审批面板仍未接入**（`src/heagent/gui/**` 零 approval 引用，无对应 story） |

### 9. 文件安全与凭证防护（Epic 36–39）· 2026-08-24

| 维度 | 要点 |
|------|------|
| 成就 | 凭证路径 deny（读 + 写）、shell 子进程 env scrubbing（`scrub_sensitive_env`）、`.heagent/` 内部状态读 deny；4 Epic / 7 story，commit `a1d886d`（25 files，+1881/−44），全量 1135 测试绿 |
| 难点 | deny 与既有工作区围栏的分层关系（不污染 git 工具）、凭证路径在 shell（`rm`/`mv`/重定向）上的等价封堵、按模式剥离而非白名单透传 |
| 做对 | deny 做成**与围栏并列的独立纯函数层**（可独立单测）、规则表刻意不开用户配置入口、内部状态只 deny 读、诚实标注非真边界 |
| 改进 | **（2026-09-18 复核）** 6 个 story 的 frontmatter 仍为 `backlog`（`36-1`/`36-2`/`36-3`、`37-1`、`38-1`、`39-1`，**仍开**）；凭证 deny 用户入口**已交付**（`.heagent/path_deny.json`，2026-09-17）；MCP stdio 子进程 scrub 仍缺（与「子进程不经沙箱」同源），**cron 一半不成立**（`cron/` 无子进程路径） |

### 10. 沙箱会话化（Epic 40）· 2026-08-26

| 维度 | 要点 |
|------|------|
| 成就 | per-run 会话工作区 + cwd 跨命令保持 + teardown、后端强度分级 `SandboxTier`（`passthrough < job < firejail < container`）、`SANDBOX_ENV_ALLOWLIST` env 豁免、CLI/GUI 三态开关；版本 0.4.0 |
| 难点 | 跨平台 cwd/退出码保持（`%CD%` 解析期展开、`pwd` 仅 POSIX）、弱后端不得降审批、诚实门（无真实后端不报路径） |
| 做对 | 复用既有 `--private` 通道与 killpg / `KILL_ON_JOB_CLOSE` 机制、`command` 单点可测缝 `_winjob_spawn`、E40-D1..D4 与 C1 全部闭合（含孤儿目录 GC） |
| 改进 | WinJob 仍零 FS / 网络隔离、Firejail 非完美边界、目录约定非安全边界——须 OS 级沙箱兜底 |

### 11. 目标驱动开发（Epic 41）· 2026-08-29

| 维度 | 要点 |
|------|------|
| 成就 | `/goal` 命令族（new/next/run/auto/status/reset）：skill 承载方法论、`cli.py` 薄机制、逐 story 独立会话、`goal-advance` cron 无人值守；commit `81264bb` / `08a4294` / `2f53406` |
| 难点 | 会话边界 = story 边界（fresh context + 阈值清窗续跑）、机器只扫三个标记的健壮性、无人值守下的显性失败 |
| 做对 | 明令禁止 `goal.py` / Pydantic `GoalState` / runs.jsonl（方法论归文本）、run 观测经 `SubAgent(metadata)` 透传、41-D1~D4 全部闭合 |
| 改进 | **（2026-09-18 复核：均已闭合）** goal 跨进程锁由 E41-D5 补齐（`persist.file_lock` + `_goal_mutex`，`855d135`）；GUI `/goal` 输出转发与取消由 E41-D7 收口（`44ab001`） |

### 12. BMad 技能包运行时（Epic 42）· 2026-09-01

| 维度 | 要点 |
|------|------|
| 成就 | 可安装可验证的技能包运行时：`he-*` canonical + `bmad-*` 别名、按需读 step/references/templates/assets/scripts、不跳步的单步执行、manifest 哈希锁；42-1~42-5（FR1~FR8），commit `6168100` |
| 难点 | 五对象职责切分（Package / Catalog / Resolver / Runner / Importer）、包根围栏复用 vs 内部状态读限的取舍、导入幂等与显式失败 |
| 做对 | 分层单一职责 + 复用 `resolve_under_root`（刻意不接 `check_read_denied` 以免误伤技能目录）、原子锁 + SHA-256 入口哈希、冲突不静默 |
| 改进 | **（2026-09-18 复核：仍开）** 资源读取竞态已转出为独立 story，Epic 46.2 以 `O_NOFOLLOW` 加固最终组件；中间目录替换 / 可信导入 snapshot / OS sandbox 仍未闭合（§17.4-A1） |

### 13. 目标级工作流（Epic 43–46）· 2026-09-01

| 维度 | 要点 |
|------|------|
| 成就 | `WorkflowOrchestrator` + checkpoint / 暂停恢复 / 幂等提交、Token 分段 rollover 与恢复信封、目标级 CLI 运维与审计、`scripts/quality_gate.py` 五门 + CI `goal-smoke`；Epic 46 TOCTOU 评估 + `O_NOFOLLOW` 加固；4 Epic / 11 story |
| 难点 | 状态所有权切分（`GOAL.md` 看板 vs `workflow.json` 阶段）、「事务结束才 checkpoint」、rollover 的累计量与窗口量分离、恢复不注入完整历史 |
| 做对 | 路由 / 阈值 / 幂等一律确定性代码裁决（LLM 不得决定阶段或伪造完成）、损坏状态显性失败（`blocked`/`failed`）、质量门单一入口 fail-fast |
| 改进 | **（2026-09-18 复核）** 45-1/45-2 **确认仍无 story 文件**（该 epic 仅 `45-3`）、spec-45-3/46-1 已在归档提交中删除或改名（仅存 git 历史）；`engine/workflow.py` legacy 相位机**归档仍待排期**；Epic 46 后续 backlog 仍开（descriptor-relative / snapshot / OS sandbox） |

### 14. 声明式 BMad 敏捷工作流（Epic 47）· 2026-09-01 → 2026-09-15

| 维度 | 要点 |
|------|------|
| 成就 | `/goal` 升级为 Goal→Epic→Story 全声明式流水线：`.heagent/workflows/workflow.md` + 角色 SKILL.md 承载方法论，`engine/workflow_runner.py`（单步 / story loop / resume / gate）+ `engine/artifacts.py`（产物契约）+ `engine/agile.py`（review/retro/correct-course）；47-1~47-10 |
| 难点 | 方法论与确定性边界的分离到底、产物契约校验（frontmatter + 固定章节 + Given-When-Then + TBD 拒收）、同 Epic 批次并行与 checkpoint 恢复 |
| 做对 | Agile Contract 钉死「`sprint-status.yaml` 是 Epic/Story 状态唯一写目标」「一 Story 一会话 WIP=1」「产物缺失/非法/冲突必须显式停止」；deferred 台账改为按归属 epic 归档 |
| 改进 | **（2026-09-18 复核）** E47-D1 已修（`cc8cb3f`）但**施动者未唯一归因仍开**（LOW）；**Step 07 迭代预算已闭合**（`max_iterations: 100`，`d7dc758`）；`skill_update` 遇富正文技能拒绝改写**仍开** |

### 15. 架构优化周期（Phase 0–5，非 BMad 流程）· 2026-09-21–22

> 6 阶段按本地方案推进（每阶段 spec 先写后批、逐边界全量门禁 + 提交）；档案归 `implementation-artifacts/arch-optimization-cycle/`（总方案 + phase0..5，执行记录并入各文件）。

| 维度 | 要点 |
|------|------|
| 交付 | Phase 0 基线冻结与文档治理；Phase 1 组合根/运行配置收敛（`ResolvedRuntimeConfig`、`SandboxDecision`）；Phase 2 loop façade 化（策略拆五模块、终态唯一 reducer `mark_terminal`）；Phase 3 workflow 解耦（确定性内核迁 `goal/application.py`，cli_goal 991→680）；Phase 4 基础设施分层（`tools/sandbox/` 包、MCP `client`+`registry_bridge`、skills 四文件、子进程监督内核统一 cap_channel/reap_subprocess、safe-open 单点 `open_text_under_root`）；Phase 5 事件契约 v2（`duration_ms`/`error_kind` + workflow_step_* 事件）+ 4 新 benchmark + 文档收口（extending/troubleshooting/goal-workflow/frame 4.15） |
| 难点 | monkeypatch 缝三类断点（默认参数绑定废模块属性缝、实例级 setattr 依赖 self. 调用点、字符串路径随迁改写）；行为冻结与「统一语义」的张力（V1–V4 逐项协商授权）；engine→events.protocol 新反向边的无环论证 |
| 做对 | 每边界一次全量门禁——三次真红被门禁抓住（reap 缝失效 / 实例 patch 拦截点丢失 / 契约测试空扫假绿）；**benchmark 首跑抓出两个生产路径真 bug**（resolve_under_root 相对 root 恒拒、safe-open 二次 join root）——单元测试全用绝对 tmp_path 漏掉的组合；spec 先批后执行 + 偏差逐条留档（Change Log） |
| 改进 | 提交全部在本地 master 未 push——CI（Linux 3.11）尚未验证平台矩阵；`_on_run_failed` façade 路径 run_failed 无耗时（恒 0）；story batch 事件为整批粒度（均挂台账） |

### 16. 网络入口三周期（Epic 48–50）· 2026-09-22 – 2026-09-27

> **来源（逐条可查，不做推测式回顾）**：Epic 48 按其正式回顾摘录；Epic 49 / 50 依据各自周期目录的交付与评审产物摘录。Epic 50 的评审已合并为 `epics/epic-50-网页控制台周期/reviews.md`，其回顾见同目录 `retrospective-epic-50.md`（2026-09-27 补做）。状态口径以 `sprint-status.yaml` 为准。

| 维度 | 要点 |
|------|------|
| 交付 | **Epic 48 · TCP 网络接口（2026-09-22 建立并同日交付，6 story）**：`network/protocol.py`（请求/成功/失败模型 + 黄金 JSONL）+ `network/tcp_server.py`（`asyncio.start_server` 生命周期）+ `cli_tcp.py`（`TcpAgentHandler` / `build_server_config` / `tcp-server` 子命令）+ `network/exposure.py`（回环判定单点）；`network/` 运行期不依赖 `cli` / `agent` / `providers` / `engine`。**Epic 49 · HTTP 网页入口（2026-09-23，6 story）**：`network/http_*` + `cli_http.py` + 包内 `web/`（自启动监听 / 就绪门禁 / SSE 流式运行与取消重连 / Host-Origin 同源防线 / 安全响应头 / 静态资源白名单）。**Epic 50 · 网页控制台（2026-09-23 建立 → 09-24 实现 → 09-27 收口，8 story 均 `done`，retrospective 已补做；含 09-24 追加的 50-8 体验优化轮）**：工作区一等化 + 项目注册表 + 会话持久化与会话 API + 配置四层来源与只读面板 + 闸门约束下的项目 `.env` 保真写（备份 / 冲突 / 审计）+ 两栏 UI 与真实浏览器验收。 |
| 难点 | 协议 / 传输层与 agent 彻底解耦（`network/` 运行期零反向依赖，被架构契约测试钉住）；**「非等待式」是限额的语义要求而非实现细节**（`Semaphore` 无 `try_acquire` ⇒ 限额退化成排队，名额记账必须用幂等集合，整数计数会在迟到任务上减成负数）；**三个危险默认值被实测证伪**（在途限额 / `click.FloatRange` 放行 `nan`·`inf` / 裸 `logger.*` 抛异常会把 `agent_error` 改写成 `server_error`）；相近命名通道必须显式区分（TCP JSONL ≠ `rollout.jsonl`）；只有真浏览器 + 计算样式才看得见的缺陷（作者级 `display` 压过 `hidden` 属性，且 `node.click()` 绕过命中测试）。 |
| 做对 | `close()` 坚持「有界返回 + warning + 结算登记」（无法强杀时如实写进 docstring，而非假装干净）；`_safe_log` 单点收口 + 注入式测试（Epic 48 共 10 个变异体全部精确变红后按 sha256 逐字节还原）；配置 / 协议各自唯一读取点（`tcp_*`、`HTTP_*`）；收口分两轮（先实现、后收口）并把评审发现当场分成「已修 / 未修如实登记」两栏；Epic 50 写通道沿用全项目纪律（fail-closed 校验 + 备份 + 审计 + 冻结边界 + 前端不硬编码键名）。 |
| 改进（2026-09-24 复核） | ① **Epic 48 回顾自己点名的「5 条缺口只进 `frame.md`、未进活动台账」已处理**——2026-09-23 补登活动台账，其中「运行栈日志非观测故障免疫」「入口日志未脱敏」当日闭合（**Z-D10 / Z-D11**，2026-09-24 已按归属 epic 回填 `epics/epic-48-TCP网络接口周期/deferred-work.md`），「TCP 入口不写 rollout」仍在活动区（**A7**）。② **Epic 50 的 retrospective 已按 Epic 48 先例在收口时补做**（2026-09-27：`epic-50-网页控制台周期/retrospective-epic-50.md` + `epic-50-retrospective: done`）；Epic 49 仍未补做（`optional`）。③ Epic 50 两轮收口评审的发现被如实分成两栏：**3 条已闭合**（`Z-D13` / `Z-D14` / `Z-D15`，2026-09-24 回填 `epics/epic-50-网页控制台周期/deferred-work.md`）与 **7 条仍开**（活动台账 **A8~A14**，其中 **A11「非回环运行姿态 + cron 跨会话后置执行」标 `blocked` 待人裁决**）。**2026-09-28 复核**：这 7 条的后续状态——3 条已闭合（运行时归因与兜底族 `a1f7c67`、高影响键风险标记 = `RESOURCE_CEILINGS`、写入通道四类残余四面处置）、1 条已闭合（非回环运行姿态 ① 裁定维持现状 + cron ② 已闭合 ⇒ 两半均已了结，2026-09-28 状态归一）、余 3 条仍在活动区（跨项目并发无全局上限 / 控制台阻塞 I/O / 浏览器级 UI 验收）；活动区实测共 **7 条**（2026-09-28 闭合 A4 后再减 1）；同日第六轮按裁定再闭合 5 条（跨项目并发 / 控制台阻塞 I/O / 浏览器验收 / 宿主 GUI 拉起面 / 原生窗口判据）⇒ **2 条**；第七轮交付 A1④、第八轮按裁定闭合 A1、第九轮按裁定归档 A6 ⇒ **0 条**。④ 立场不变：三个入口**都不是安全边界**（无认证 / 无 TLS；回环判定与启动告警只是提示），须 OS 级沙箱兜底。 |

### 1x. 收尾周期（Epic 51–57）· 2026-09~10

> 2026-10-27 补记：正式综合回顾未并入本文，各周期 retro / 评审产物在各自目录——Epic 51（10-23 收口）、52（10-09 交付）、53（10-24 walkthrough 收口）、54（retro 10-24）、55（回溯登记）、56（两期 retro）、57（在途）。状态以 `sprint-status.yaml` 为准。

---

## 二、周期详解（迁自 consolidated-overview.md §一–十六）

> 迁移注记：①「§17.x」指针指 consolidated-overview.md（2026-11-15 重组为 epic-overview.md，§十七重编为 §一/1.x）对应节；②「deferred-work-archive.md」指针指本文 §三；③「A 编号登记表」在 epic-50 周期 deferred-work.md；④ 仅标题降级，内容逐字节保留。

### 一、项目与 BMad 迭代模型

#### 1.1 HeAgent 是什么

自改进 AI Agent 框架（单进程异步 Python 库），灵感来自 NousResearch **Hermes Agent**，但以「**重新实现核心设计模式来理解自主 Agent 架构原理**」为目标，非功能复刻。核心差异化 = **简洁可读 + 插件化架构**（Hermes 核心类 >10,000 行 → HeAgent 目标核心循环 <1,500 行）。

**五子系统**：① Provider 抽象层（多模型 + 回退链 + 凭证轮换）② 工具调用引擎（声明式注册 + 并行调度 + 安全护栏）③ 自学习闭环（SKILL.md / MEMORY.md + USER.md）④ 上下文管理（自动压缩、迭代预算、会话持久化）⑤ 子 Agent 委派（并行隔离）。

**技术栈**：Python 3.11+、Pydantic v2、httpx、openai/anthropic SDK、全异步、pytest + pytest-asyncio、ruff、mypy。外部运行时依赖仅 6 个（openai / anthropic / tiktoken / pydantic / pydantic-settings / mcp）。

#### 1.2 迭代模型（BMad Method）

组织单元 = **周期（Cycle）**，一个周期 = 一个独立目标集（一组 FR），产出独立规划文档：

| 周期类型 | 触发 | 产物目录 | 编号空间 |
|----------|------|----------|----------|
| 主线周期 | 新产品方向 / 大功能集 | `_bmad-output/<cycle>/`（brief→prd→architecture→epics→stories） | Epic 沿主线编号递增 |
| 集成周期 | 接入外部系统（如 MCP） | 同上，独立 brief/prd | Epic 编号延续主线 |
| 补丁周期 | 计划外技术债 / 缺陷 | 补丁 spec 按归属 epic 归入 `_bmad-output/epics/<周期>/<epic-NN-主题>/`（原 `patches/` 2026-09-15 解散）+ 各周期 `deferred-work.md`（已闭合项归档） | spec 文件，不占 Epic 编号 |
| epic 外增量 | 架构演进（engine 治理层） | 直接落代码 + `frame.md` 记录 | 按 P0/P1… 分批 |

**标准工作流**：`brief → prd → architecture → epics → stories → quick-dev → code-review`，每步对应一个 `bmad-*` skill。技术债走 **deferral 机制**（发现 → 分类 fix-now/defer → 记录 `implementation-artifacts/deferred-work-archive.md` 活动台账 → 开专门 spec 收尾写 Resolution 关闭 → **按归属 epic 归档**到各周期 `deferred-work.md`）。

#### 1.3 统一编号体系（2026-07-23 整合消歧）

此前 sprint-status 分散在 6 个文件，存在 **Epic 14 编号冲突**（MCP v1→v2 升级准备 vs MCP Client V2 写操作治理）。合并后编号规则：

| 起始编号 | 周期 | 说明 |
|---------|------|------|
| Epic 1–10 | baseline | 主线 MVP + 自学习闭环 |
| Epic 11–13 | mcp（阶段一） | MCP 工具桥接 + GitHub E2E + 安全声明 |
| Epic 14 | mcp（阶段二） | MCP v1→v2 升级准备（pin / 隔离层 / 测试基线） |
| Epic 15–18 | mcp（阶段三） | 写操作治理 / Resources / Prompts / 内置工具扩展 |
| Epic S1–S4 | sandbox-hardening | Sandbox profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离 |
| Epic 19–20 | robustness-hardening | 文件锁 / Cron 范围 / WinJobBackend / 覆盖率 90% |
| Epic 21–24 | quality-engineering | Coverage 工程化 / Benchmark / Docker 硬化 / CI 安全 |
| Epic 25–28 | gui | GUI 终端界面（流式聊天 / 工具可视化 / 管理面板 / 可观测性） |
| Epic 29–35 | interaction | 交互与可扩展层（审批 / 会话恢复 / 斜杠命令 / Hooks / Plan Mode / 角色配置 / CLI 收尾） |
| Epic 36–39 | file-safety-hardening | 文件安全与凭证防护（凭证路径 deny / scrub_sensitive_env / SafetyGuard 凭证拦截，2026-08-24 交付） |
| Epic 40 | sandbox-session | 沙箱会话化执行（会话目录 / 后端强度分级 / env 豁免 / SandboxSession，2026-08-26 规划） |
| Epic 41 | goal-driven-dev | /goal 启动 skill 执行工作流（机制薄代码 + skill 承载方法论 + cron 无人值守，2026-08-29 已交付） |
| Epic 42 | skill-package-runtime | 可安装、可验证的声明式技能包运行时（FR1-FR8：包发现 / 别名解析 / 资源围栏读取，2026-09-01 交付） |
| Epic 43–46 | goal-workflow-continuation | 目标级编排/恢复、Token 分段、运维收口与技能资源 TOCTOU 评估（2026-09-01；Epic 43–46 评估/实现已完成） |
| Epic 47 | declarative-bmad-agile-workflow | Goal→Epic→Story 产物契约、BMad 角色包、Markdown workflow/step、Runner、声明式 `/goal`、Review/Retrospective/Correct Course 与两 Story 冒烟（2026-09-01） |
| Epic 48 | tcp-network-interface | **⚠️ REMOVED (2026-09-27)**：TCP 网络接口已删除（commit `4217b5d`，~2,800 行代码）。删除原因：使用率极低、维护成本高、HTTP 入口已充分覆盖需求。历史文档保留于 `epics/epic-48-TCP网络接口周期/` |
| Epic 49 | http-web-entry | HTTP 网页入口：`network/http_*` + `cli_http.py` + 包内 `web/`（自启动监听 / 就绪门禁 / SSE 流式运行与取消重连 / Host-Origin 同源防线 / 安全响应头 / 静态资源白名单）。本机单用户，无认证无 TLS（2026-09-23 交付；6 Story done） |
| Epic 50 | web-console | 网页控制台（Epic 49 显式推迟的切片）：工作区一等化 + 项目注册表 + 会话持久化 + 四层配置来源与只读面板 + 闸门约束下的项目 `.env` 写入（保真写 / 备份 / 冲突 / 审计）+ 两栏 UI 与真实浏览器验收 + 安全收口与文档同步（2026-09-23 建立，2026-09-24 实现，**2026-09-27 收口**；**8 Story 均 `done`**，四轮收口评审已出并**放行**（评审/验收文档 2026-09-26 合并为单文件 `reviews.md`），retrospective 已补做）。**2026-09-24 追加 Story 50-8**（收口后体验优化轮：会话列表精简 / 原生目录选择 / 布局调整 / 设置面板瘦身 / 读取结果只显示文件名），该 story 同时是**本 Epic 后续新需求的统一落点** |
| Epic 51 | goal-workflow-trusted-delivery | `/goal` 与 workflow 可信交付优化：预检与统一状态视图、显式事件/转换表、结构化执行证据、真实质量 Gate、步骤级审批、多 workflow 冻结、受控 GoalScript 与写集证明的安全并行（2026-09-29 建立；8 Story 全部 `done`，**2026-10-23 收口**；A25–A28/A33/A37–A39 全部闭合归档） |
| Epic 52 | safe-parallel-story-executor | goal 工作流安全并行 Story 执行器：声明门控批次（七条件）+ policy 层写集围栏 + 宿主 Git 写集审计与单向撤销闩，让 `max_parallel_stories` 真实生效；worktree 物理隔离为后续增强层（2026-10-09 建立 / 交付；5 Story 全部 `done`，retrospective 已补做） |
| Epic 53 | container-sandbox-tier | 容器沙箱档：`SandboxTier.CONTAINER` 从预留枚举落为 `DockerRunner` 后端（shell 进容器，`--network=none` 默认 + bridge 显式开启，镜像 pin digest，不可用则显性降级 Passthrough）；**OS 级强隔离兜底、非绝对边界**，弱后端一律不得审批降级（NFR-2）（2026-10-20 立项；3 Story 均 `review`，2026-10-21 交付判据；期二 MCP stdio 进容器 / 审批降级接入挂 `deferred-work.md` D53-1 / D53-2，待用户裁定） |
| Epic 54 | websocket-entry | WebSocket 入口与 HTTP/SSE 并存：单 run 事件订阅、ring buffer 游标续传、`cancel`/`ping` 命令、`ack`/`error` 帧、Origin 防线、独立 per-run 连接限额和有界关停；无认证、无 TLS、回环不等于可信（4 Story done；交付物随压缩提交 `98ef6d8` 于 2026-10-24 入库并随 0.8.2 发布） |
| Epic 55 | CLI 旁路 | 终端旁路事件中枢：`/api/cli/ws` 跨轮次只读观众席流，只挂本地 listener（终端事件可能含文件内容）；无 story（回溯周期），随 `98ef6d8` 入库并随 0.8.2 发布 |
| Epic 56 | WS 对外入口 | HTTP/WS 完全分离，WS 独立 ASGI app（默认 9001，唯一 breaking）；对外模式强制 Bearer token（fail-closed）+ TLS 可选；期二双 listener 并存与端点可见性（8 story，2026-10-24 交付，两期 retro 各一份） |
| Epic 57 | retro 遗留清理 | 清空 epic-52/53/54 retro 的 7 条 open items 后收口（2026-10-26 立项，`in-progress`） |

**FR 编号空间**（互不冲突，引用须写全限定）：主线 `FR-1~24`；MCP V1 `FR-1~11`；MCP 升级准备 `FR-1~5`；MCP V2 `FR-A1~A7 / FR-B1~B4 / FR-C1~C4`；Sandbox `FR-S1~S7`；健壮性 `FR-A1~A5 + FR-C1~C6`；质量工程 `FR-Q1~Q20`；GUI `FR-G1~G24`；interaction `FR-A1~A5 / FR-B1~B3 / FR-C~G 各 1~4`；文件安全 `FR-1~5`（本地）；沙箱会话化 `FR-1~5`（本地，FR-5 deferred）。

> 另有历史「Epic 6」编号冲突：`epics/epic-01-10-主线规划周期/epics-integration.md`（2026-06-03）自称 Epic 6=AgentLoop 全模块集成，其后被自学习周期重新占用（Epic 6=Context Files，以 sprint-status 为准）；该文视作「Epic 1-5 之后的集成补丁」历史归档。

---

### 二、全周期时间线总览

| 时间 | 里程碑 |
|------|--------|
| 2026-05-23~26 | baseline 规划冻结（brief/prd/architecture/epics），主线 Epic 1-10 定义 |
| 2026-06-08 | 自学习闭环 Epic 6-10 分解（FR-20~24） |
| 2026-06-19~20 | P0 provider 技术债收尾 + MCP Client 集成周期（Epic 11-13）启动 |
| 2026-06-23 | engine P0 loop engine runtime 落地（epic 外增量） |
| 2026-06-25 | engine P1-P5 集中落地（多 agent 角色化 + checkpoint-resume + 树形聚合） |
| 2026-06-29 | engine/agent 注释补全、loop.py 拆分、CI 质量门禁；epic-13 retrospective |
| 2026-07-01 | 工作区路径围栏收敛为 `resolve_under_root` 单一算法；FR-3 MCP 断连 auto-unregister |
| 2026-07-08 | engine sandbox 接真实后端（`CommandRunner` 抽象）；DP-4 第一半（执行前工具名拦截） |
| 2026-07-09~10 | sandbox 健壮性系列（D1/D3/D4、取消信号保留、reap 鲁棒性）；DP-4 第二半（返回内容围栏）；MCP 关停硬上界 |
| 2026-07-11 | Cron 关停硬上界 + deferred LOW 收尾——**三处同构关停硬上界补齐** |
| 2026-07-12 | MCP v1→v2 升级准备周期（Epic 14，隔离层先行）完成 + POC 验证 |
| 2026-07-14 | `.env` 优先级反转（`init > dotenv > env > secrets`） |
| 2026-07-17 | MCP Client V2 周期（Epic 15-18）：写操作治理 / Resources / Prompts / git 工具 |
| 2026-07-20 | Sandbox 硬化周期（Epic S1-S4，8 stories）交付，751/751 测试 |
| 2026-07-21 | 健壮性硬化（Epic 19-20）：文件锁 + Cron 范围 + WinJobBackend + 覆盖率 90%，797/797 测试 |
| 2026-07-22 | 质量工程深化（Epic 21-24）交付，922 测试全绿；全周期回顾 `retrospective-all-cycles.md` |
| 2026-07-23 | GUI 周期（Epic 25-28）规划冻结 + sprint-status 统一整合；GUI 12 个 story 全部 done |
| 2026-08-10~12 | **后续增量（git log 实证）**：steering/follow-up 双层循环（P0）、Dreaming 离线记忆巩固模式、`cron/expr.py` 纯叶子抽取、业务数据整合母规划 spec、用户可配置 MCP 注入签名 spec（pending）、`~/.heagent/.env` 全局配置 + `heagent init`、Windows exe 打包 + release 0.3.1 |
| 2026-08-19 | **交互与可扩展层周期（Epic 29-35）规划冻结并收官**：审批闭环 / 会话恢复 / 斜杠命令 / Hooks / Plan Mode / 自定义角色 + 成本估算 / CLI 收尾；全量 1052 测试通过 |
| 2026-08-24 | **文件安全与凭证防护周期（Epic 36-39）交付**：凭证路径 deny（读+写）/ `scrub_sensitive_env` / `.heagent/` 内部状态读 deny；commit `a1d886d`，全量 1135 测试通过 |
| 2026-08-26 | **沙箱会话化周期（Epic 40）交付**：per-run 会话工作区 + 后端强度分级 + env 豁免 + `SandboxSession` cwd 保持；版本 0.4.0 |
| 2026-08-29 | **目标驱动开发（Epic 41）交付**：`/goal` 命令族（skill 承载方法论 + `cli.py` 薄机制）+ `goal-advance` cron 无人值守；2026-09-07 拆为独立模块 `cli_goal.py` |
| 2026-09-01 | **技能包运行时（Epic 42）+ 目标级工作流（Epic 43-46）交付**：`he-*` canonical / manifest 哈希锁 / step runner；WorkflowOrchestrator + checkpoint + rollover + 审计 + `scripts/quality_gate.py`；Epic 46 TOCTOU 评估 + `O_NOFOLLOW` 加固 |
| 2026-09-09~12 | **声明式 BMad 工作流（Epic 47）主体交付**：`.heagent/workflows/workflow.md` 中文化并吸收 bmad-build 方法论、角色/模板契约重构、同 Epic Story 批次并行、sandbox 输出上限（512 KiB/通道） |
| 2026-09-14 | 对标 Codex 三项：分层上下文文件发现、机器可读事件流（`events/` + rollout / replay）、真实 tokenizer + 结构化压缩；`file_edit` 编辑原语与沙箱权限档位化 |
| 2026-09-15 | **规划产物整理**：`patches/` 解散并按归属 epic 归档（22 个 spec）、跨周期 deferred 台账按 epic 归并（E1/E4/E5/E10/E11/S-D/E40/E47 全部闭合）、story 产物按 Epic 分组；全量 1896 passed / 9 skipped |
| 2026-09-17~20 | **架构与代码优化批次**：persist/roles/frontmatter 自 engine 迁出（Z-D1/D2）、cli_init.py / goal/document.py 拆分、沙箱硬化配置接入（SANDBOX_PROFILES 等）、凭证 deny 项目级入口（F-D1）、goal 跨进程锁（E41-D5）、O_NOFOLLOW 加固（Epic 46.2）、问卷删除 + /simplify 收敛 |
| 2026-09-21~22 | **架构优化周期（Phase 0–5）交付**：组合根收敛 / loop façade / workflow 解耦（goal/application）/ sandbox·MCP·skills 三域拆分 + 子进程内核统一 + safe-open 单点 / **事件契约 v2**（duration_ms·error_kind + workflow_step_*）+ 4 新 benchmark + 文档收口（extending/troubleshooting/goal-workflow/frame 4.15）；周期档案 `implementation-artifacts/arch-optimization-cycle/`；全量 2061 passed / 90.88% |
| 2026-09-22~24 | **网络入口三周期（Epic 48-50）**：Epic 48 TCP 网络接口（6 story，09-22 建立并交付，**09-27 删除**，commit `4217b5d`）；Epic 49 HTTP 网页入口（6 story，09-23 交付）；Epic 50 网页控制台（8 story，09-23 建立 / 09-24 实现 / **09-27 收口为 `done`**，四轮收口评审已出并放行、retrospective 已补做；09-24 追加 **Story 50-8** 体验优化轮） |
| 2026-09-29~10-23 | **Epic 51-53**：Epic 51 `/goal` 与 workflow 可信交付优化收口（8 story，A25–A28/A33/A37–A39 全部闭合）；Epic 52 安全并行 story 执行器交付（5 story，写集围栏 + 宿主 Git 审计 + 单向撤销闩，四层评审 22 patch 全处置）；Epic 53 容器沙箱档落地期一（3 story，**2026-10-24 walkthrough 收口**：`DockerRunner` + 镜像 pin + 网络档 + 显性降级留痕）。同期主线小改：`/work`→`/loop` 技能改名、`/compact` 手动压缩命令、docker 档启动提示与三入口 `--sandbox` 取值平权、本地质量门补齐 bandit 并与 CI lint job 对齐 |

| 2026-10-24~26 | **网络入口收尾（Epic 53-56）与 Epic 57 立项**：Epic 53 walkthrough 收口；54/55/56 交付物随 `98ef6d8` 入库并随 0.8.2 发布（2026-10-26 版本 `0.8.3`，2026-10-29 起 `0.8.4`）；条目改名 gpt→openai、anthropic→claude（`24b0bd1`）；HTTP/WS 独立开关（`de8311b`）；Epic 57 立项（4 story 当日全 done，收口在途） |

> **文档滞后说明（2026-09-15 更新）**：`docs/iteration.md` 已补齐至 2026-09-15（含 8-9 月增量与整理记录），8 月上旬增量（Dreaming / steering / 发布）亦已回写 `sprint-status.yaml` 与各周期目录。**若本文与 `docs/iteration.md` / `sprint-status.yaml` 冲突，以后二者为准**；代码现状以 `docs/frame.md` 为准。

---

### 三、周期 1：主线 MVP 与自学习闭环（Epic 1-10，FR-1~24）

> 目录：`_bmad-output/epics/epic-01-10-主线规划周期/`。规划期 2026-05-23~26。状态：**Epic 1-10 全部 done**（37 stories + 10 retrospective）。

#### 3.1 产品定位与边界（brief，DEC-001~005）

- **定位**：个人学习项目（非商业），差异化 = 简洁可读 + 插件化，主动牺牲功能广度换代码清晰度。
- **目标用户**：作者本人（理解 Agent 架构原理）。
- **V1 范围**：Provider 抽象、工具引擎（终端/文件/网页搜索）、自学习闭环、上下文管理、子 Agent、MCP 协议集成（延后）、错误分类重试。
- **明确排除**：消息平台网关、Cron（后被 FR-24 重新纳入）、TUI（后被 GUI 周期纳入）、浏览器自动化、语音/图像生成、多租户、Web 服务端。
- **成功标准**：完整 Agent 循环、≥2 Provider 回退链、技能提炼闭环、记忆跨会话、子 Agent 委派、核心循环 <1,500 行、插件化零耦合。

#### 3.2 需求清单（prd，FR-1~19 + 自学习扩展 FR-20~24）

**Provider 抽象层（FR-1~5）**

| FR | 内容 |
|----|------|
| FR-1 | Provider 接口定义 — 统一 `BaseProvider` Protocol（send/stream/解析工具调用/元数据），返回统一 `ProviderResponse` |
| FR-2 | OpenAI Provider 实现 — 兼容端点（官方 + LM Studio）、SSE 流式、function calling/tool_use 解析 |
| FR-3 | Anthropic Provider 实现 — Claude API、流式、tool_use 解析、提示词缓存（cache_control 断点） |
| FR-4 | Provider 回退链 — 429/503 自动切换下一 Provider，全部不可用返回明确错误 |
| FR-5 | 凭证轮换 — 同 Provider 多 API Key 池，单 Key 限速自动切换；池耗尽触发 Provider 级回退 |

**工具调用引擎（FR-6~9）**

| FR | 内容 |
|----|------|
| FR-6 | 声明式工具注册 — `@tool` 装饰器自动提取名称/描述/参数 schema，加新工具不改核心循环 |
| FR-7 | 工具并行执行 — 无依赖 tool_calls 并行执行，单工具失败不影响其他 |
| FR-8 | 安全护栏 — 危险命令暂停确认、白名单/黑名单模式、拦截记日志 |
| FR-9 | 内置工具集 — 终端执行（超时默认 120s）、文件操作、网页搜索；均经 FR-6 注册可独立启停 |

**自学习系统（FR-10~12）**

| FR | 内容 |
|----|------|
| FR-10 | 技能提炼 — 成功序列提炼为 Skill 存 SKILL.md（`.heagent/skills/`），后续匹配自动注入 |
| FR-11 | 事实记忆管理 — MEMORY.md 跨会话记录，新会话自动加载，关键词匹配去重 |
| FR-12 | 用户画像 — USER.md 记录技术背景/偏好，影响回复风格与技术深度 |

**上下文管理（FR-13~15）**

| FR | 内容 |
|----|------|
| FR-13 | 自动上下文压缩 — 接近窗口阈值（默认 80%）自动摘要，保留最近 N 轮 |
| FR-14 | 迭代预算控制 — 默认 50，每工具调用耗 1 次，达上限强制最终响应 |
| FR-15 | 会话持久化 — JSON 保存，session ID 恢复，含完整消息历史与工具调用记录 |

**子 Agent 委派（FR-16~17）**：FR-16 子 Agent 生成与执行（独立上下文+预算，默认继承全部工具）；FR-17 并行子 Agent 编排（独立线程并行，单失败不阻塞）。

**MCP（FR-18）**：工具发现与调用，MVP 后延后（后由 MCP 周期承接全量交付）。

**错误处理（FR-19）**：错误分类与差异化重试——速率限制→轮换/回退；认证→跳过；瞬态→指数退避最多 3 次；非瞬态→立即返回。

**自学习扩展（epics-self-learning，FR-20~24，2026-06-08）**

| FR | 内容 | Epic |
|----|------|------|
| FR-20 | Context Files 自动加载 — 扫描 `.heagent/CONTEXT.md`、AGENTS.md、CLAUDE.md（优先级 CONTEXT > AGENTS > CLAUDE）注入 `<project-context>` 块 | 6 |
| FR-21 | SOUL.md 人格系统 — 全局 `~/.heagent/SOUL.md` + 项目级两级，项目级覆盖全局，作为系统提示词 `<identity>` 第一段 | 7 |
| FR-22 | Memory Nudge 记忆提醒 — 系统提示词注入静态提醒 `<memory-nudge>` 块，可配置开关 | 8 |
| FR-23 | Skill Curator 技能策展 — 追踪 usage_count/last_used，过期（默认 30 天）归档 `.heagent/skills/.archive/`；工具 `skill_curate`/`skill_archive` | 9 |
| FR-24 | Cron 定时调度 — asyncio 后台调度器，5-field cron 表达式（**手写解析器，不引入 croniter**），JobStore 持久化，工具 `cron_add`/`cron_list`/`cron_remove` | 10 |

**系统提示词注入顺序（冻结）**：`identity > user system > project-context > skills > memory-nudge > memory > profile`

**非目标**：非 Hermes 复刻；不做网关/Cron/TUI/浏览器自动化/语音图像/多用户/Web 服务端。**反指标**：SM-C1 功能数量（宁缺毋滥）、SM-C2 性能吞吐（不做并发优化）。

#### 3.3 架构冻结决策（architecture，8 项）

| 决策点 | 冻结方案 |
|--------|----------|
| 模块间通信 | 直接调用 + Middleware 管道混合（`typing.Protocol` + 链式 `async def process(request, next)`），不用事件总线 |
| 工具注册 | `@tool` 装饰器 + `ToolRegistry` 单例，自动生成 JSON Schema，内置与 MCP 工具统一 |
| Provider 抽象 | 单协议 + 外层 `ProviderChain`（BaseProvider 只管通信；Chain 管回退与轮换，职责单一） |
| 配置管理 | Pydantic BaseSettings + `.env`，启动即类型校验失败 |
| 记忆存储 | 项目级 `.heagent/` 目录（skills/memory/user/sessions），项目隔离 |
| 子 Agent 隔离 | `asyncio.create_task` 同进程异步任务 + `gather` 并行，不做进程级隔离 |
| 日志 | stdlib `logging` + `dictConfig`，各模块 `getLogger(__name__)` |
| 数据模型 | 一律 Pydantic BaseModel，不用 dict/dataclass |

**异常层级**：`HeAgentError` → `ProviderError` / `ToolError` / `SafetyViolation` / `BudgetExceeded`。
**重试**：指数退避+抖动 `min(base*2^attempt + jitter, max_delay)`，base=1s / max=30s / retries=3；仅重试 429/503/网络超时。
**模块依赖 DAG（冻结）**：

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ─────────────┘
```

（注：DAG 后经 engine 增量扩展——engine 依赖 types/exceptions/tools.safety，被 agent 依赖；`tools/mcp/` 为后续集成周期新增。）

**FR→文件映射**：FR-1→`providers/base.py`；FR-2/3→openai/anthropic；FR-4/5→chain.py；FR-6/7→tools/decorator+registry；FR-8→tools/safety；FR-9→tools/builtins/*；FR-10→memory/skills；FR-11→memory/facts；FR-12→memory/profile；FR-13→context/compressor；FR-14→agent/loop；FR-15→context/session；FR-16/17→agent/sub；FR-19→exceptions+重试中间件。

#### 3.4 Epic 划分与覆盖矩阵

| Epic | 名称 | 覆盖 FR | Stories | 状态 |
|------|------|---------|---------|------|
| 1 | 项目基础设施与 LLM 通信 | FR-1~5, FR-19 | 1.1~1.8 | done |
| 2 | 自主 Agent 核心循环 | FR-6~9, FR-14 | 2.1~2.6 | done |
| 3 | 对话持久化与上下文管理 | FR-13, FR-15 | 3.1~3.2 | done |
| 4 | 自学习记忆系统 | FR-10~12 | 4.1~4.3 | done |
| 5 | 多 Agent 并行编排 | FR-16~17 | 5.1~5.2 | done |
| 6 | Context Files 自动加载 | FR-20 | 6.1~6.3 | done |
| 7 | SOUL.md 人格系统 | FR-21 | 7.1~7.3 | done |
| 8 | Memory Nudge 记忆提醒 | FR-22 | 8.1 | done |
| 9 | Skill Curator 技能策展 | FR-23 | 9.1~9.4 | done |
| 10 | Cron 定时调度 | FR-24 | 10.1~10.5 | done |

#### 3.5 关键决策记录（prd DEC-001~006）

PRD 精简 ~2 页、FR 全局编号；19 FR 覆盖 7 子系统；MCP 延后 MVP 后（标注 NOTE FOR PM 建议尽快实现）；内置工具精简为 3 个（对比 Hermes 40+）；4 个假设全部确认 V1 最简方案。

---

### 四、周期 2：MCP Client 集成一（Epic 11-13，独立 FR-1~11）

> 目录：`_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段一，原 `mcp-client/`）。规划期 2026-06-20。状态：**Epic 11-13 全部 done**（8 stories）。

#### 4.1 周期意图

在既有 `ToolRegistry` / `AgentLoop` 之上加一层 MCP client 适配器，让 HeAgent 从「自带 18 个内置工具」升级为「可连接生态无限外部工具」，以 **GitHub 只读**（列 open issue + 代码搜索）为首个真实验收场景。V1 只消费 MCP **Tools 原语**，不接 Resources / Prompts（后由 V2 周期补齐）。

#### 4.2 需求清单（FR-1~11 / NFR-1~7）

| 组 | FR | 内容 |
|----|----|------|
| 连接与生命周期 | FR-1 | 支持 stdio + Streamable HTTP 双 transport |
| | FR-2 | 生命周期与 `AgentLoop` 绑定（启动建立/退出回收）；工具发现须在首次构建工具列表前完成或 lazy 回退 |
| | FR-3 | 失败按既有异常层级降级不崩溃；区分「连接建立失败」vs「运行时断连」 |
| 发现与桥接 | FR-4 | 动态发现 Tools → 映射 `ToolSchema` → 注册进 `ToolRegistry` |
| | FR-5 | 结果桥接为 `ToolResult`，与内置工具执行路径一致（含并行 `asyncio.gather`） |
| | FR-6 | 多 server 命名去歧义（server 名前缀 namespace） |
| 声明式配置 | FR-7 | 项目根 **`.mcp.json`**（对齐 Claude Code/Cursor）；stdio `{command,args,env}` / http `{url,headers}`；无配置 → 纯内置模式不报错 |
| | FR-8 | `${ENV}` 插值；鉴权凭据走环境变量，不写配置明文 |
| GitHub 验收 | FR-9 | 官方 `github/github-mcp-server` 两类只读 E2E：「列 open issue」+「代码搜索」 |
| 安全 | FR-10 | 外部 MCP server 归入既有安全声明，CLAUDE.md 更新覆盖 MCP |
| | FR-11 | MCP 工具受与内置工具同等安全约束；返回内容同等不可信；`SafetyGuard` 扩展为架构探索项（DP-4） |

**NFR**：NFR-1 全异步；NFR-2 零回归（18 内置工具 + 既有测试全绿，覆盖率不降）；NFR-3 版本可控（`mcp>=1.27,<2`，后评审统一 `>=1.28,<2`，握手封 `MCPClientManager` 内部）；NFR-4 启动性能（多 server 连接发现不显著拖慢）；NFR-5 可观测（stdlib logging）；NFR-6 错误隔离（单 server 失败不影响其他）；NFR-7 代码规范（PEP8/Pydantic/120 行宽/3.11+，tool 层禁从 `agent/` 导入）。

#### 4.3 架构决策（architecture，决策 A-H）

- **A. 模块落点**：`tools/mcp/`（纠正老 `providers/mcp.py` 占位——MCP 暴露的是工具不是模型）；DAG 合规，`cli.py` 是唯一装配点。
- **B. 发现/注册路径**：复用 `registry.register()`（零扩展）；**eager + 并发 + 隔离 + 每服务器连接超时**（否决 lazy——LLM 只能从发给它的 schema 列表选工具）；`__aenter__` 用 `asyncio.gather(..., return_exceptions=True)` 在 `loop.run()` 之前完成。
- **C. 生命周期绑定**：`MCPClientManager` 作 async ctx mgr，CLI `async with` 包住 AgentLoop；`__aexit__` unregister 全部 MCP 工具 + `AsyncExitStack` 关闭 session/子进程；否决「AgentLoop 改 async ctx mgr」（零回归）。
- **D. 协议封装边界**：`initialize` 握手 / `protocolVersion` 协商 / transport 细节全封在 manager 内；AgentLoop 只见 `ToolSchema`/`ToolResult`；为 2026-07-28 stateless 迁移留接口；错误映射 `ToolError`，不引入新异常。
- **E. Transport 分派**：`_connect(entry)` 内部按配置类型分派 stdio / Streamable HTTP；否决正式 Transport Protocol 抽象（仅 2 种，YAGNI）。
- **F. Namespace**：工具名 = `<server>__<tool>`（双下划线）；server 名规整化（小写 + 非字母数字 → `_`）。
- **G. 结果/错误映射**：`CallToolResult.content` V1 text-only（多块 `\n` 连接）；`ImageContent` → `[image]` 占位、`EmbeddedResource` → `[resource: uri]` 占位；`isError=True` → 抛 `ToolError` → `ToolResult(is_error=True)`。
- **H. 配置加载**：独立 `MCPConfig` Pydantic 模型 + `load_mcp_config(path)`；`${ENV}` 插值加载时展开，未设变量 fail-fast；Settings 门控 `mcp_enabled` / `mcp_config_path`。

**验证**：16 项 checklist 全绿，READY FOR IMPLEMENTATION。**评审 rubric verdict**：pass-with-fixes（NFR-4 阈值、NFR-2 覆盖率基线、FR-9 schema 锚点等修复项）。

#### 4.4 Epic 拆分

| Epic（主线编号） | 标题 | FRs | Stories |
|---|---|---|---|
| 11 | MCP 工具桥接（核心能力） | FR-1~8 | 1.1~1.5（dep-skeleton / config-env-interpolation / tool-mapping-bridge / client-manager-lifecycle / cli-mcp-wiring） |
| 12 | GitHub 只读验收 | FR-9 | 2.1（github-readonly-e2e） |
| 13 | 安全边界与开源可用 | FR-10/11 | 3.1~3.2（safety-statement-mcp / opensource-config-docs） |

依赖：Epic 1 独立可用；Epic 2、3 构建于其上、彼此独立。内部链：`1.1 → (1.2 ∥ 1.3) → 1.4 → 1.5`。

#### 4.5 关键决策与回顾

- **决策 D1-D7**：走通用 MCP client（否决 GitHub 专用）；只接 Tools 原语；V1 只读优先；受众「自用为主 + 开源友好」；pin `mcp>=1.27,<2`；声明式 `mcpServers` 配置；MCP server 归入既有不可信边界。
- **决策 DP-1~6**：配置落点项目根 `.mcp.json`（DP-1）；鉴权 `${GITHUB_TOKEN}` 环境变量插值（DP-2）；验收清单 = 列 open issue + 代码搜索（DP-3）；**DP-4 SafetyGuard 对 MCP 声明为主 V1 不扩展**（成为跨文档 deferred 决策锚点，后两半于 2026-07-08/10 交付）；验收 server = 官方远程 Streamable HTTP（DP-5）；记忆整合 = Vision 非 V1（DP-6）。
- **Epic 13 回顾**：安全立场同构落地；deferred 编号化（DP-4）跨文档引用；`.mcp.json.example` + README 就位；零契约改动。教训：新不可信组件套用既有安全立场；deferred 要编号+跨文档引用；收尾 epic 价值在可被采用。

---

### 五、周期 3：MCP v1→v2 升级准备（Epic 14，独立 FR-1~5）

> 目录：`_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段二，原 `mcp-v2-upgrade/`）。2026-07-12。状态：**Epic 14 done**（3 stories + POC 验证）。

#### 5.1 周期意图

官方 Python SDK `mcp` v2.0.0 stable 目标 2026-07-27、协议规范 2026-07-28 RC（breaking）将重塑 client 侧 API。本周期**不接新原语**，而是兑现 mcp-client brief 已埋的迁移预留——把会被 v2 冲刷的调用点抽象成隔离层，v2 stable 落地时切换局限于该层内部、Epic 11-13 零回归。

**逐行核查命中 5 个 breaking 点**：① `session.initialize()` 删除（转 stateless）② `send_ping()` deprecated（冲击 FR-3 断连探测）③ `mcp.types` 拆独立 `mcp-types` 包 ④ `list_tools()` 签名变 + `inputSchema`→`input_schema` ⑤ `call_tool()` 返回字段 snake_case。

#### 5.2 需求清单（FR-1~5 / NFR-1~6）

| FR | 内容 |
|----|------|
| FR-1 | SDK pin floor 提到 `mcp>=1.28.1,<2`（对齐 v1 线最新 stable） |
| FR-2 | 在 `MCPClientManager` 内建隔离层，封装 5 个 v2-sensitive 调用点（握手/健康探测/工具发现/工具调用/类型导入） |
| FR-3 | 文档化断连 auto-unregister 在 v2 stateless 下的等价机制选型（候选 A 被动注销 / B 主动 discover / C 过渡占位）；安全立场不可退化 |
| FR-4 | 迁移测试基线——Epic 11-13 的 `tests/test_mcp_*.py` 改动后全绿 |
| FR-5 | 文档化 v2 stable 落地时的切换路径（只产出路径文档，不含实际切换） |

**NFR**：NFR-1 零回归；NFR-2 封装局部化（隔离层对外接口 v1→v2 切换 diff 为空）；NFR-3 不可信边界立场延续（DP-4 两半不退化）；NFR-4 纯 v1 准备（不引入 v2 alpha 依赖）；NFR-5 继承约束（异步 + DAG）；NFR-6 可观测。

#### 5.3 架构决策（AD-1~6）

**Design Paradigm：Anti-corruption layer（Adapter，函数式收敛模块）**。新建 `tools/mcp/session_api.py` 导出 `handshake` / `ping` / `list_tools` / `call_tool` + 类型别名 + 字段兼容函数（`input_schema_of` / `result_is_error`）；`manager.py`/`mapping.py` 禁止直接触碰 SDK session 方法。

- **AD-1** 隔离层收敛全部 5 个 v2-sensitive 调用点。
- **AD-2** 隔离层对外接口 v1→v2 切换 diff 为空；`mapping.py` 零改动。
- **AD-3** FR-3 v2 等价机制 = **C 过渡占位 + v2 切 A 被动**（v1 保留 `send_ping`；v2 时 handler 闭包 `try/except call_tool` 失败调 `_unregister_server`；异常只包 `call_tool` 永不包 `bridge_result`）。
- **AD-4** 纯 v1 准备边界，交付不依赖 v2 时点。
- **AD-5** 零回归基线 + `session_api.py` 新增单测。
- **AD-6** DAG + 异步 + 类型：禁从 `agent`/`mapping` 导入（mapping→session_api 单向）；passthrough SDK 原生类型不新造模型。

**POC 就绪度报告**（实装 mcp 2.0.0b1）：类型 import 实测 `from mcp_types import` OK；**SDK v2 保留 legacy `initialize`**（修正预测）；`call_tool` 返回 union（duck-type 兼容）；`send_ping` b1 仍在；**FR-3 A 语义实现 + 测试通过；`mapping.py` 零改动 ✓、`session_api` 对外签名 diff 空 ✓（AD-2 兑现）**；Open question 实测答案 = **保持 `ClientSession`，不迁 `Client(mode='auto')`**。client 切换约 1 story（<1 人日），比预测更轻。

#### 5.4 Epic 拆分

单 epic（Fast path）：**Epic 14「MCP v1→v2 升级准备（隔离层先行）」**，线性依赖 14-1（pin）→ 14-2（隔离层）→ 14-3（测试基线）。FR 覆盖 5/5。

---

### 六、周期 4：MCP Client V2（Epic 15-18，FR-A~C + 内置工具）

> 目录：`_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段三，原 `mcp-client-v2/`）。2026-07-17。状态：**Epic 15-18 全部 done**（11 stories，16/16 FR 覆盖）。

#### 6.1 周期意图

V1（Tools-only）的延续，把 V1 刻意冻结的三处缺口补齐，落在既有 `MCPClientManager` 扩展点上，**不重写 V1、不破坏既有不变量**：① 写操作无治理（call_tool 对只读/破坏性一视同仁）→ 把 `Tool.annotations` 透传进 `ToolSchema` → 喂 `PolicyEngine`（destructive→审批 / readOnly→放行 / 缺省 fail-safe）；② Resources 原语未消费（application-controlled，on-demand）；③ Prompts 原语未消费（user-controlled，CLI slash 命令）。

**差异化**：写操作治理的**确定性**（危险判定交给代码不交给 LLM）；诚实安全立场延续（annotations 是 server 自声明、不可信，须 OS 级沙箱兜底）。

#### 6.2 需求清单（FR-A1~A7 / FR-B1~B4 / FR-C1~C4）

**Epic A 写操作治理**：

| FR | 内容 |
|----|------|
| FR-A1 | `ToolSchema` 新增可选字段 `annotations`（默认缺省），HeAgent 自有 Pydantic 模型（避免 types 层上浮 mcp 依赖） |
| FR-A2 | `mapping.mcp_tool_to_schema` 透传 `tool.annotations` → `ToolSchema.annotations` |
| FR-A3 | `PolicyEngine` 按 `destructiveHint=true` → `PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在执行闸门前；授权沿用 `metadata.approved_tools`（含 `*` / `__mcp__`） |
| FR-A4 | `readOnlyHint=true` 放行自动调用；**显式策略（`approval_tools`/`approval_mcp_tools`）优先于 annotation**，反向不成立 |
| FR-A5 | 缺 annotations → **fail-safe 需确认**（保守默认视为非只读 → APPROVAL_REQUIRED） |
| FR-A6 | 治理确定性可单测——存在不调用任何 LLM 的单元测试断言 (ToolCall, annotations) → 固定 PolicyVerdict |
| FR-A7 | `idempotentHint`/`openWorldHint` 透传存储、LLM 可见，但 V2 不据此改变裁决 |

**Epic B Resources**：FR-B1 `list_resources` 内置工具（无连接返回空列表）；FR-B2 `read_resource` 按 server + URI 取回内容（URI 不存在 → ToolError；非文本 text-first 降级）；FR-B3 **on-demand 不自动注入**；FR-B4 返回内容经 DP-4 第二半同等围栏标记后透传。

**Epic C Prompts**：FR-C1 `list_prompts` 发现；FR-C2 CLI 交互 `/mcp-prompt <server> <name> [key=value ...]` 渲染注入；FR-C3 模板参数化缺必填显式报错；FR-C4 渲染输出经同等围栏标记后注入。

**UJ 锚定**：UJ-1 沙箱 repo 建 issue 走审批；UJ-2 问资源 on-demand 取 URI；UJ-3 `/mcp-prompt` 渲染代码审查模板。**反指标 SM-C1**：不过度审批只读工具（fail-safe 须精准作用于「缺信号」而非「有 readOnly 信号」）。

#### 6.3 架构决策（ARCHITECTURE-SPINE，AD-1~8）

**Design Paradigm：brownfield 扩展**（在既有扩展点上加固+接入，非新机制）。承重约束：**确定性逻辑交给代码、不交给概率模型**。

- **AD-1** annotations 经 `ToolSchema` 显式 kwarg 注入 PolicyEngine（`evaluate_tool_call(call, *, context=None, schema=None)`）；两个 evaluate 调用点（正常路径 + ledger 缓存命中复核）都传；否决污染 ToolCall / 注入 registry / 塞 RunContext.metadata 三种备选。
- **AD-2** 注解驱动 fail-safe 审批裁决：步 0 前置闸门 `schema=None`（V1 内置/未知工具）→ 跳过注解裁决回既有路径，**fail-safe 绝不误伤 19 个内置工具**；①显式策略命中即审批 ②destructive → 审批 ③readOnly → 不审批 ④MCP 缺 annotations → 审批。
- **AD-3** 治理裁决确定性、纯函数化、可单测，不触达任何 LLM。
- **AD-4** `MCPClientManager` 持有 `self._sessions: dict[str, ClientSession]`（B/C 前置）；session 唯一属主是 `_server_loop` task，`_sessions` 是只读查找表；断连按 **flag-before-pop**（先摘键再退 transport）；桥接调用见键移除 → 规范化 `ToolError("MCP server '%s' disconnected")`。
- **AD-5** Resources 走「manager 注册的聚合桥接工具」路径：`mcp__list_resources` / `mcp__read_resource`（`mcp` 作聚合 server token，双下划线 → `_is_mcp_tool` 自动识别 → **全量继承 V1 MCP 门控**）；自声明 `readOnlyHint=True`；**签名钉死 `read_resource(server: str, uri: str)`，`server` 必填**（收紧 PRD FR-B2 跨 server 歧义）；无 MCP 配置时不注册。
- **AD-6** 三原语统一 on-demand + 同等不可信围栏（**`guard_content(text) -> str` 提升为 `mapping.py` 公共函数**）——Tools（`bridge_result`）/ Resources（`mcp__read_resource`）/ Prompts（slash 分发器）一律调用同一公共围栏，标记透传、不阻断。
- **AD-7** Prompts 经最小 CLI slash 分发器（OQ-4 定稿）：`_run_chat` REPL 在 `input()` 与 `loop.run_stream()` 间加最小分发器（`user_input.startswith("/")` → 查命令表分发，`/mcp-prompt` 首条命令）；推荐接入 (i)：`_mcp_lifecycle` 返回 manager 实例。
- **AD-8** 治理闸门 + 围栏均非真正安全边界（annotations 不可信，恶意 server 可谎报 `readOnlyHint=true`）；须 OS 级沙箱兜底；CLAUDE.md/frame.md 安全声明更新覆盖。

**约定**：`ToolSchema.annotations` 覆盖四 hint，不透传第 5 非决策字段 `title`；`annotations` 缺省本身不触发 fail-safe（仅「MCP 工具 + 缺 annotations」触发）；Stack 不新增运行时依赖。

#### 6.4 Epic 拆分（11 stories）

- **Epic A「写操作治理」**（FR-A1~A7，无前置依赖、完整自包含）：A.1 annotations 数据管线 / A.2 PolicyEngine 注解裁决闸门 / A.3 零回归护栏 + 治理确定性验证 / A.4 安全声明更新。
- **Epic B「Resources on-demand」**（FR-B1~B4，自引入 `_sessions` + `guard_content`）：B.1 `_sessions` 映射（flag-before-pop 断连语义）/ B.2 `mcp__list_resources` 聚合桥接 / B.3 `mcp__read_resource` + `guard_content` 公共围栏 / B.4 安全声明。
- **Epic C「Prompts CLI slash」**（FR-C1~C4，依赖 B 的 `_sessions` + `guard_content`；最弱腿、预算吃紧首选 defer 候选）：C.1 manager prompts 入口（不注册为 LLM 工具）/ C.2 slash 分发器 + `/mcp-prompt` / C.3 渲染围栏 + 安全声明。

**AR-1~10**（架构承重决策编号）与 **NFR-1~7**（诚实立场/确定性/上下文预算/同等围栏/语义重叠披露/零回归/不过度审批）贯穿各 story。

---

### 七、周期 5：Sandbox 硬化（Epic S1-S4，FR-S1~S7）

> 目录：`_bmad-output/epics/epic-S1-S4-沙箱硬化周期/`。2026-07-20。状态：**Epic S1-S4 done**（8 stories，S4-1 skipped；24 个 sandbox 专项测试，751/751 全绿）。

#### 7.1 周期意图

既有沙箱执行管道（`SANDBOX_REQUIRED` 裁决 → `CommandRunner` 抽象 → `FirejailBackend`）是「空壳」——profile 不映射参数、普通用户无配置入口、firejail 不可用时不提示。本轮把管道填满。

**五个问题**：① `sandbox_profile` 是死字段（profile 经裁决后丢弃，不同 profile 跑相同参数）；② 普通用户无配置入口（只能写 Python 代码注入 runner）；③ firejail 不可用时不提示（首次 shell 调用才 FileNotFoundError）；④ timeout/cancel 只杀直系子进程（后台子孙成孤儿）；⑤ workspace_root 未映射 OS 级隔离（只有纯 Python 逻辑围栏）。

#### 7.2 需求清单（FR-S1~S7 / NFR-S1~S6）

| FR | 内容 |
|----|------|
| FR-S1 | `FirejailBackend` 接受 `profiles: Mapping[str, Sequence[str]]`，按 profile 名映射 firejail 参数；不存在时仅用 `extra_args`（不抛错） |
| FR-S2 | `ToolExecutor.execute_in_sandbox` 把 profile 经 contextvar 注入（`bind_sandbox_profile` + `get_sandbox_profile`） |
| FR-S3 | `FirejailBackend.__init__` 用 `shutil.which` 检测可用性；不可用 warn + 后续 `run()` 降级 Passthrough；`.available` 属性暴露 |
| FR-S4 | `.env` 支持 `SANDBOX_BACKEND`（passthrough/firejail）+ `SANDBOX_FIREJAIL_PATH`；CLI `--sandbox` flag（CLI 优先）；`EngineContainer.default()` 自动构造 |
| FR-S5 | Linux 平台 `start_new_session=True` + `os.killpg` 替代 `proc.kill()`；非 Linux 零改动 |
| FR-S6 | `FirejailBackend` 自动映射 `workspace_root` 为 `--private=<ws>`（插在 `extra_args` 与 `profile_args` 之间） |
| FR-S7 | executor 四类 emit 事件（started/completed/failed/blocked）details 新增 `sandbox_backend` + `sandbox_pid`（经专用 `_sandbox_pid_slot` contextvar 回填） |

**NFR**：NFR-S1 零回归（727 测试绿）；NFR-S2 安全声明诚实（Firejail 仍非完美边界）；NFR-S3 平台透明（无 firejail 优雅降级不 crash）；NFR-S4 确定性单测（`_build_argv` 纯函数）；NFR-S5 模块边界（tools/sandbox + engine/executor + config + cli + container，不反依赖）；NFR-S6 每 FR ≥1 单测 + 1 集成测试。

#### 7.3 架构决策（AD-S1~S7）

- **AD-S1** profile→args 映射在 `FirejailBackend` 内部，不扩 `CommandRunner.run` Protocol 签名；`_build_argv` 纯函数。
- **AD-S2** profile 经 `bind_sandbox_profile` contextvar 注入（与 `_command_runner_slot` 同构），`PassthroughRunner` 对 profile 透明。
- **AD-S3** 不可用时降级 Passthrough 不抛异常；`SANDBOX_BACKEND=firejail` 且不可用时 emit 的 `sandbox_backend` 仍标 `"firejail"`（用户意图）。
- **AD-S4** `EngineContainer.default()` 读 Settings 自动构造 runner；CLI flag 优先于 `.env`。
- **AD-S5** `sys.platform == "linux"` 守卫进程组 killing；非 Linux 路径不变；killpg 失败走 wait。
- **AD-S6** workspace_root 非空时 `--private=<ws>` 生成于 `extra_args` 与 `profile_args` 之间。
- **AD-S7** emit 事件新字段从 contextvar 读取；PID 用独立 `_sandbox_pid_slot`，每次调用前 reset。

**关键决策 D-1~3**：profile→args 映射放代码不放 `.env`（安全配置）；profile 经 contextvar 注入不扩 Protocol 签名；`SANDBOX_BACKEND=passthrough` 时 runner 为 None（走快速路径）。

#### 7.4 Epic 拆分

| Epic | 主题 | FR | Stories |
|------|------|----|---------|
| S1 | Profile-aware sandbox | FR-S1, S2 | S1-1（profiles dict + `_build_argv`）/ S1-2（contextvar 注入） |
| S2 | 可用性 & 配置入口 | FR-S3, S4 | S2-1（`shutil.which` 检测 + 降级）/ S2-2（.env/CLI 配置） |
| S3 | 纵深加固 | FR-S5, S6 | S3-1（Linux 进程组 kill）/ S3-2（workspace → `--private`） |
| S4 | 可观测 & 文档收尾 | FR-S7, NFR-S2 | S4-1（emit 事件扩展，**skipped**）/ S4-2（安全声明同步） |

**边界**：不做非 firejail 新后端、不引入 `SandboxProfile` 类、不沙箱非 shell 工具、不自动安装 firejail、CI 不真跑 firejail（用 mock）。**Deferred**：`--seccomp`/`--caps` 高级参数、资源限额、MCP server/cron 子进程接入沙箱。

---

### 八、周期 6：健壮性与质量硬化（Epic 19-20，FR-A1~A5 + FR-C1~C6）

> 目录：`_bmad-output/epics/epic-19-20-健壮性硬化周期/`。2026-07-21。状态：**Epic 19-20 done**（9 stories；46 专项测试，797/797 全绿）。

#### 8.1 周期意图

此前 17 个 Epic 已交付、deferred work 全部关闭。本轮不开发新功能，夯实已有系统：方向 A（健壮性/安全）补齐跨进程文件锁、Cron 范围表达式、Windows 沙箱；方向 C（质量/工程化）拉高覆盖率 80%→90%、CI 多平台矩阵、静态分析加严、性能基准。

**六个问题**：A1 跨进程持久化无文件锁（`os.replace` 竞态，可能读到半写文件）；A2 `CronParser` 不支持范围（`1-5`）与 `*/15`；A3 OS 沙箱 Linux-only；C1 覆盖率基线低（80%）；C2 CI 矩阵单一（仅 ubuntu + 3.11）；C3 静态分析偏软（缺复杂度门禁、bandit、pip-audit、性能基准）。

#### 8.2 需求清单

**方向 A（健壮性，FR-A1~A5）**：

| FR | 优先级 | 内容 |
|----|--------|------|
| FR-A1 | P0 | `atomic_write_text(path, content, *, lock=False, lock_timeout=5.0)` 可选进程间文件锁（POSIX `fcntl.flock` / Windows `msvcrt.locking`）；锁文件独立（`foo.json.lock`）；`EngineContainer(enable_file_locks=False)` 默认关闭 |
| FR-A2 | P1 | `CronParser` 支持 `1-5`、`*/15`、`1-30/10` 组合；非法表达式 → `ValueError`；与 croniter 参数化测试对齐 |
| FR-A3 | P1 | 新增 `tools/sandbox.py::WinJobBackend`（Windows Job Objects，`KILL_ON_JOB_CLOSE` 自动清子孙；`CREATE_SUSPENDED` race-free 绑定）；CLI `--sandbox winjob`、env `SANDBOX_BACKEND=winjob` |
| FR-A4 | P2 | 安全声明更新（CLAUDE.md / frame.md 同步文件锁、Cron 扩展、Windows 沙箱） |
| FR-A5 | P2 | sandbox 死代码清理（`_PROFILE_MAP`、`SandboxProfileSlot`、`build_argv` 无未使用分支） |

**方向 C（质量工程化，FR-C1~C6）**：

| FR | 优先级 | 内容 |
|----|--------|------|
| FR-C1 | P0 | 覆盖率 80%→90%（CI `--cov-fail-under=90`，每模块 ≥80%）；补齐 executor 并发 lease、persist 锁路径、observability buffer 满等异常路径 |
| FR-C2 | P1 | CI 全组合矩阵 `ubuntu/windows/macos-latest` × `3.11/3.12/3.13`（9 jobs，`fail-fast: false`）；sandbox 测试仅原生平台跑真后端；三平台覆盖率合并 |
| FR-C3 | P1 | 静态分析硬化：Ruff 扩展 `B`（bugbear）、`C90`（max-complexity=15）、`S`（排除 S101/S104）、`SIM`、`TCH`；CI 加 `bandit -r src/`（零 MEDIUM+）+ `pip-audit`（不报 CRITICAL） |
| FR-C4 | P2 | 性能基准：token 估算 vs tiktoken 真值误差 ≤20%、压缩率 ≥50%、100 工具注册 <10ms；CI 警告不硬拦 |
| FR-C5 | P2 | 复杂度治理：`agent/loop.py` 评估拆分（不强求，C901 注释可接受） |
| FR-C6 | P2 | 文档与版本号同步（pyproject bump、frame/iteration/CLAUDE/sprint-status 更新） |

**NFR**：NFR-1 向后兼容（新 kwargs 全带默认值）；NFR-2 平台可移植（stdlib）；NFR-3 无新运行时依赖（不引入 croniter/portalocker/filelock）；NFR-4 确定性（纯函数 + 锁语义 + 门禁确定性）。

#### 8.3 架构决策（AD-1~6）

- **AD-1** 文件锁：`.lock` 文件与目标文件分离（避免 `os.replace` 后 fd 指向旧 inode 锁失效）；锁超时默认 5 秒抛 `OSError`；`EngineContainer.default()` 默认隐式关闭。
- **AD-2** Cron parser：`_parse_field` → `_expand_field` pipeline，不改 5 字段结构；`*`/逗号走快路径；非法输入 `ValueError`。
- **AD-3** WinJobBackend：ctypes 调 kernel32，惰性加载；`Popen(["cmd", "/c", command])`；`JOB_OBJECT_UILIMIT_HANDLES` 设 `:0`；不用 WSL2/Docker（依赖太重）；仅进程级隔离（无 FS 隔离）。
- **AD-4** CI 矩阵 3×3=9 jobs + 1 optional integration job；覆盖率 artifact → `coverage combine`。
- **AD-5** 静态分析渐进启用：`B` 全量 fix、`C90` 超标加 `# noqa: C901` + 理由、`S` 排除 S101/S104、`SIM` auto-fix、`TCH004` 修循环导入。
- **AD-6** 覆盖率策略：先 `--cov-report=json` 出 gap 按大小排序逐个补。

**接口契约变更**：`atomic_write_text` 新增 `lock`/`lock_timeout`；`EngineContainer` 新增 `enable_file_locks`；`WinJobBackend` `available()` + `run(command, *, timeout, workspace_root)`。安全立场不变：全部 defense-in-depth。

#### 8.4 Epic 拆分

- **Epic A「健壮性硬化」**（FR-A1~A5）：A.1 跨进程文件锁 / A.2 Cron 范围表达式 / A.3 WinJobBackend / A.4 安全声明 + 死代码清理。
- **Epic C「质量工程化」**（FR-C1~C6）：C.1 覆盖率 90% / C.2 CI 多平台矩阵 / C.3 静态分析硬化 / C.4 性能基准 + 复杂度治理 / C.5 文档与版本号同步。

两 Epic 正交可并行。决策定稿：D1 单文件 fcntl/msvcrt 锁、D2 Windows Job Objects（纯 stdlib ctypes）、D3 扩展现有 parser（不引入 croniter）、D4 覆盖率 90% CI 硬拦。

---

### 九、周期 7：质量工程深化（Epic 21-24，FR-Q1~Q20）

> 目录：`_bmad-output/epics/epic-21-24-质量工程周期/`。2026-07-22。状态：**Epic 21-24 全部 done**（18 stories，20 FR 交付，零业务代码改动，922 测试全绿）。

#### 9.1 周期意图

质量基线 911 tests / 90% 行覆盖率 / ruff+mypy 零告警 / 三级 CI 门禁，「骨架完整但工具链存在结构性半成品」——benchmark 框架已装未接入（手工 `perf_counter()` 而非 `pytest-benchmark` fixture）、coverage 配置散落 CI 脚本不可本地复现、Docker HEALTHCHECK 指向不存在的 HTTP 端点。目标：质量工程从「能用」推到「业界 best practice」。

**约束（关键）**：**不改动 `src/heagent/` 下任何产品代码**（纯工程配置周期）；不引入新运行时 Python 依赖（dev 可加）；测试数量不减少、覆盖率不下降；CI 总耗时 ≤ 基线 1.5 倍。

**决策日志 D1-D3**：D1 纯工程配置周期（风险隔离、可独立 revert）；D2 覆盖率目标保持 88%（本次不提升）；D3 benchmark 用 GitHub Actions artifacts 持久化（零成本、零新依赖）。

#### 9.2 需求清单（FR-Q1~Q20 / NFR-Q1~Q4）

**Coverage 工程化（Epic 21）**：FR-Q1 `[tool.coverage]` 配置段落入 pyproject.toml（`source`/`branch`/`omit`/`exclude_lines`/`fail_under=88`）；FR-Q2 CI coverage job 迁移到读 pyproject.toml；FR-Q3 HTML/XML 报告上传 artifact（保留 7 天）。

**Benchmark 重构 + CI（Epic 22）**：FR-Q4 10 个 benchmark 测试改 `pytest-benchmark` fixture（单次调用用 `benchmark.pedantic()`）；FR-Q5 `[tool.pytest-benchmark]` 配置（`min-rounds=5`、`max-time=1.0`、`storage=./benchmark-data/`、`save=ci`、`autosave=true`）；FR-Q6 `.gitignore` 添加 `benchmark-data/`；FR-Q7 CI benchmark job（`pytest --benchmark-only --benchmark-autosave` + artifact）；FR-Q8 下载上次 artifact，`compare` 退化 >20% 标黄（warning 不 fail）。

**Docker 修复（Epic 23）**：FR-Q9 新增 `.dockerignore`；FR-Q10 HEALTHCHECK 改为 `CMD python -c "import heagent; print('ok')"`（进程存活性）；FR-Q11 base image `python:3.11-slim@sha256:<digest>` 锁定。

**CI 效能 + 安全左移 + pre-commit + ruff（Epic 24）**：FR-Q12 `setup-python` 启用 `cache: pip`；FR-Q13 CI test matrix 增加 Python 3.14-dev（`continue-on-error: true`）；FR-Q14 CodeQL job（每周一 9:00 UTC scheduled，仅 `security` 查询套件）；FR-Q15 dependency-review job（PR 触发）；FR-Q16 pre-commit 卫生 hooks（trailing-whitespace/end-of-file-fixer/check-yaml/check-toml/check-merge-conflict/check-added-large-files 500KB）；FR-Q17 bandit hook（`-ll`）；FR-Q18 ruff `select` 新增 `PLC`/`RUF`/`PT`/`PIE`；FR-Q19 新规则告警逐条修复或豁免（含注释）；FR-Q20 ruff `[format]` 段（`quote-style="double"`、`indent-style="space"`、`line-ending="lf"`）。

**NFR**：NFR-Q1 不修改 `src/heagent/` 下任何 `.py`；NFR-Q2 CI 总耗时 ≤ 1.5 倍基线（约 6→9 分钟上限）；NFR-Q3 911 测试全量通过、覆盖率 ≥88%；NFR-Q4 新增配置项有注释、无未文档化魔法数字。

#### 9.3 架构决策（AD-1~7）

AD-1 benchmark 退化阈值 20%（共享 CI runner 波动大）；AD-2 compare 用 warning 不 fail（避免假阳性损害 CI 可信度）；AD-3 CodeQL 仅 security + 每周（全量查询回报率低）；AD-4 Python 3.14-dev `continue-on-error`（预发布不稳定不阻塞）；AD-5 HEALTHCHECK 用 `import heagent` 而非 HTTP（CLI 库无 HTTP 服务，进程存活性最诚实）；AD-6 `[format]` line-ending 设 `lf`（Windows 开发者用 `core.autocrlf true` 适配）；AD-7 本轮不提升覆盖率 fail_under（88% 是已达成基线，提升需伴随实际测试补写，超出纯配置周期范围）。

#### 9.4 Epic 拆分（18 stories，全部可并行）

- **Epic 21 Coverage 工程化**：21.1 `[tool.coverage]` 段落 / 21.2 CI 迁移 / 21.3 HTML artifact。
- **Epic 22 Benchmark 重构**：22.1 fixture 重构 / 22.2 配置 + .gitignore / 22.3 CI benchmark job / 22.4 CI compare（下载失败优雅跳过）。
- **Epic 23 Docker 硬化**：23.1 .dockerignore / 23.2 HEALTHCHECK 修复（`docker ps` 显示 healthy）/ 23.3 base image digest 锁定（注释标注日期和原因）。
- **Epic 24 CI 效能与安全**：24.1 pip 缓存 / 24.2 3.14-dev / 24.3 CodeQL（独立 workflow）/ 24.4 dependency-review / 24.5 pre-commit 卫生 / 24.6 bandit hook / 24.7 ruff 规则扩展 / 24.8 告警修复。

**风险与缓解**：benchmark fixture 重构破坏既有断言（逐测对比语义差异，多轮 median vs 单次 perf_counter）；CodeQL 首次大量告警（先手动评估、必要时只开 security-and-quality）；新 ruff 规则数百条告警（先 `ruff check --statistics` 评估，豁免以 `per-file-ignores` 为主）。

---

### 十、周期 8：GUI 终端界面（Epic 25-28，FR-G1~G24）

> 目录：`_bmad-output/epics/epic-25-28-GUI界面周期/`。2026-07-23。状态：**Epic 25-28 全部 done**（12 stories；retrospective 为 optional——按 sprint-status 单一权威）。参考 `_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md`。

#### 10.1 周期意图

为 HeAgent 增加终端 GUI（TUI），把交互从「命令行 REPL」升级为「结构化终端应用」。**GUI 是纯消费者**——不改 `AgentLoop` 核心，仅消费 `run_stream()` + `EventBus`。

**CLI 三大体验短板**：① 流式输出与工具调用混在一起难区分；② 管理操作无界面（技能/Soul/Cron/记忆需手动编辑文件）；③ 运行历史不可见（子 Agent 委派、运行树、事件日志）。

**范围**：流式聊天（Markdown）、工具调用折叠卡片、管理面板（技能/Cron/记忆）、可观测性（事件日志/运行树/状态栏）、斜杠命令（`/model` 等）、`[gui]` optional extra。**非目标**：Web 界面、多会话并发、图形化配置向导、移动端/远程访问、修改 `AgentLoop`。

**决策日志 D1-D4**：D1 GUI 周期不改核心模块；D2 选 Textual（TUI）而非 Web（async-native 无需桥接）；D3 分 4 个 Phase 交付；D4 `heagent gui` 子命令而非 `--gui` flag。

#### 10.2 需求清单（FR-G1~G24 / NFR-G1~G8）

**Phase 1 流式聊天（Epic 25）**：FR-G1 `heagent gui` 启动全屏 TUI；FR-G2 LLM 文本流式逐字显示；FR-G3 Markdown 渲染；FR-G4 用户/Agent 消息视觉区分；FR-G5 状态栏实时显示模型名/迭代数/Token；FR-G6 执行期间输入框禁用 + 状态栏「运行中」。

**Phase 2 工具可视化 + 斜杠命令 + 中断（Epic 26）**：FR-G7 工具调用折叠卡片（状态：执行中/已完成/失败）；FR-G8 卡片展开显示参数与结果；FR-G9 失败红色标记；FR-G10 显示执行耗时；FR-G11 `/model` 命令（无参列出 Provider，带参切换）；FR-G12 `/mcp-prompt`（行为与 CLI 一致）；FR-G13 `Ctrl+C` 中断当前运行；FR-G14 `Ctrl+L` 清空消息列表。

**Phase 3 管理面板（Epic 27）**：FR-G15 页面导航（Tab 或 F1-F6）；FR-G16 技能管理表格 + 详情/归档/删除；FR-G17 技能创建弹窗；FR-G18 Cron 管理表格 + 增删；FR-G19 记忆面板（事实记忆 + 用户画像）。

**Phase 4 可观测性（Epic 28）**：FR-G20 运行历史树（supervisor → sub-agent）；FR-G21 选中运行查看详情；FR-G22 未完成运行「恢复运行 (resume)」；FR-G23 事件日志实时流；FR-G24 日志暂停/恢复滚动 + 按事件类型过滤。

**NFR**：NFR-G1 核心模块零行改动；NFR-G2 `[gui]` optional extra；NFR-G3 `textual>=1.0,<2.0`；NFR-G4 GUI 代码全在 `src/heagent/gui/`；NFR-G5 现有 922 测试全量通过；NFR-G6 80×24 终端可用；NFR-G7 Agent 后台 Worker 运行 UI 不卡顿；NFR-G8 GUI 覆盖率 ≥ 50%（bridge 层与状态管理必须覆盖）。

**Epic 依赖**：Epic 25 硬前置；26 依赖 25；27 可与 26 并行；28 依赖 25（+27 页面导航）。

#### 10.3 架构（architecture，AD1-AD5）

**技术选型冻结**：Textual 1.x、`heagent gui` Click 子命令、`[gui]` optional extra、`AgentLoop.run_stream()` → `App.post_message()` 流式桥接、`EventBus.subscribe(GuiEventObserver)`、Textual `reactive` + Pydantic 状态管理。

**模块结构**（`src/heagent/gui/`）：`__init__.py`（`gui_main()`）、`app.py`（`HeAgentApp`）、`bridge.py`（`AgentBridge` 核心胶水）、`cli.py`、`state.py`（`GuiState`）+ `screens/`（chat/skills/cron/memory/runs/event_log）+ `widgets/`（message_list/tool_card/status_bar/event_log/input_area）。

**依赖方向（冻结）**：`gui/` 单向依赖 `agent/ engine/ providers/ tools/ memory/ cron/ context/`；核心模块**禁止**导入 `gui/`。

**核心数据流**：用户输入 → `AgentBridge.submit(prompt)` → `run_stream()` 产出 `StreamEvent` 经 `post_message` → ChatScreen 按 event.type 分派（text→追加、tool_call→插卡片、tool_result→更新卡片、done→恢复状态栏/输入框）；引擎事件 → `GuiEventObserver` → StatusBar/EventLogScreen；页面导航 F1-F6。

**关键组件**：AgentBridge（submit/cancel，CancelledError → `AgentInterrupted`）；GuiState（Pydantic：model_name/iteration/max_iterations/token_usage/is_running/active_tool/last_error）；管理面板经 ToolRegistry 调 `skill_*`/`cron_*` 工具而非直接写文件（AD2）；RunsScreen 用 `RunStore.build_run_tree(limit=50)`。

**决策**：AD1 bridge 用 `asyncio.create_task` 不阻塞 UI；AD3 重用 `cli.py` 的 `_build_provider()`（提取共享 `_bootstrap.py`）；AD4 会话暂不持久化；AD5 状态栏用 `reactive` 而非轮询 EventBus。

#### 10.4 Epic 拆分与 Story 主题（12 stories）

| Epic | 主题 | FR | Stories |
|------|------|----|---------|
| 25 | 流式聊天（最小可跑） | FR-G1~G6 | 25-1 项目骨架+CLI 入口 / 25-2 流式聊天引擎（AgentBridge + GuiState + MessageList）/ 25-3 Markdown 渲染与执行状态 |
| 26 | 工具可视化 + 斜杠命令 | FR-G7~G14 | 26-1 工具调用卡片（三态标题栏、展开参数/结果、截断 2000 字符）/ 26-2 斜杠命令（`/model`/`/mcp-prompt`/`/clear`/`/help`，Tab 补全）/ 26-3 中断与快捷键（Ctrl+C/Ctrl+L/Esc） |
| 27 | 管理面板 | FR-G15~G19 | 27-1 页面导航（F1-F6，switch_screen）/ 27-2 技能管理（DataTable + 详情/新建/归档/删除，直接调 handler 不走 Agent）/ 27-3 Cron + 记忆面板 |
| 28 | 可观测性 | FR-G20~G24 | 28-1 事件日志面板（`[HH:MM:SS] {event_type} run=... iter=... tool=...`，Space 暂停滚动）/ 28-2 运行历史树（`build_run_tree`，状态图标，`run.completed` 自动刷新）/ 28-3 运行详情与恢复（水平分割，`AgentBridge.resume(run_id)`） |

> ⚠️ **一致性提示**：story 文件内「依赖」字段编号存在错位（多处写 `24-1`/`25-1`/`26-1` 等），按文件语义应分别为 `25-1`/`26-1`/`27-1`/`28-1` 等——sprint-status.yaml 的 key 为权威。

---

### 十一、周期 9：交互与可扩展层（Epic 29-35，FR-A~G）

> 目录：`_bmad-output/epics/epic-29-35-交互扩展周期/`。2026-08-19 规划冻结并收官。状态：**Epic 29-35 全部 done**（27 个 story 项登记于 sprint-status；无独立 story 文件，quick-dev 执行；全量 1052 测试通过，ruff/mypy 零错误）。

#### 11.1 周期意图

引擎底座（Provider 容错 / 工具系统 / 四类记忆 / PolicyEngine-ToolExecutor-ledger-store / MCP 三原语 / cron / dream / Textual GUI）已就绪；对照 Claude Code 与 hermes-agent 功能审查发现短板集中在**面向使用者的交互与可扩展层**。目标：把 HeAgent 从「架构实验场」推进为「可日常使用的 agent 工具」，**不触碰 `AgentLoop` 核心循环**——全部能力复用既有基础设施。

**非目标**：多模态、Web API/多租户、审批跨 run 永久授权（本轮仅 per-run）、Hooks 完整事件过滤/参数模板引擎。

**决策 D1-D4**：D1 审批以可注入 `ApprovalHandler` 落地，默认 None（auto-deny 等价现状），零核心回归；D2 授权写 `RunContext.metadata["approved_tools"]`（per-run 粒度）；D3 会话恢复 `--continue` + `--resume <session_id>`，仅 CLI 装配层改动；D4 编号延续主线 Epic 29 起。

#### 11.2 需求清单（FR-A~G）

**Epic 29 运行时审批闭环（P0-①，FR-A1~A5）**：`ApprovalHandler` 协议 + `ApprovalDecision`（`engine/approval.py`）；`EngineContainer` 注入（默认 None = auto-deny）；`APPROVAL_REQUIRED` 且配置 handler 时先询问——APPROVE 写 `approved_tools` 后**重新裁决**执行（同 run 同类不再重复询问），DENY 等同现状阻断；CLI 交互注入 stdin 询问（非 tty 保持 auto-deny）；`Settings.approval_tools` 声明审批范围。

**Epic 30 会话恢复入口（P0-②，FR-B1~B3）**：CLI `--continue`（最近会话）/ `--resume <session_id>`；`_run_chat` 复用 session_id（复用 `SessionStore.recent_session_ids`/`load`）；无历史降级新会话并提示。

**Epic 31-35（P1/P2，FR-C/D/E/F/G）**：31 斜杠命令注册表 + 用户自定义命令（`slash.py` + `.heagent/commands/*.md`）；32 Hooks 系统（`engine/hooks.py`：`PreToolUse` 可阻断 / `PostToolUse` / `SessionStart` / `SessionEnd`，`.heagent/hooks.json`）；33 Plan Mode（内置只读工具补 `readOnlyHint`，`PolicyEngine.allowed_tools` 白名单收敛，排除 MCP 工具）；34 配置文件驱动角色（`.heagent/agents/*.md` → `RoleSpec`）+ 成本估算（`model_pricing`）；35 CLI 体验 + 技术债收尾（`web_fetch` 接 `guard_content`、cron expr 诊断、`init --project`、readline 历史）。

**NFR-1~5**：零核心回归（未配置时行为不变）；核心零改动（新增集中在 `engine/approval.py`/`hooks.py`、`slash.py`、`tool_execution.py` 局部、`cli.py` 装配）；Pydantic 模型禁 raw dict；全 async（审批询问走 `asyncio.to_thread(input)`）；安全立场诚实（审批非安全边界）。

#### 11.3 Epic 拆分与交付（7 Epic，story 项 29:4 / 30:3 / 31-35:各4）

| Epic | 主题 | 核心交付 |
|------|------|----------|
| 29 | 运行时审批闭环 | `engine/approval.py`：`APPROVAL_REQUIRED` 从「死判决」变为可交互授权 |
| 30 | 会话恢复入口 | CLI `--continue` / `--resume` 复用已有会话 |
| 31 | 斜杠命令系统 | `slash.py` 注册表 + 用户自定义命令（`.heagent/commands/*.md`） |
| 32 | Hooks 系统 | `engine/hooks.py` 四事件钩子（PreToolUse 可阻断） |
| 33 | Plan Mode / 只读模式 | readOnlyHint 补齐 + `allowed_tools` 白名单收敛 |
| 34 | 配置驱动角色 + 成本估算 | `.heagent/agents/*.md` 加载 RoleSpec + `model_pricing` 成本展示 |
| 35 | CLI 体验 + 技术债收尾 | web_fetch 围栏 / cron 诊断 / init --project / readline 历史 |

#### 11.4 回顾要点（retrospective，2026-08-19）

**做对**：① 复用既有设施、`AgentLoop` 零侵入（验证 design.md「新增能力不改 AgentLoop」成功标准）；② fail-safe 方向一致（审批异常→DENY、hook 崩溃/超时→阻断、Plan Mode 排除不可信 MCP readOnlyHint、无效价格表→空表不崩溃）；③ 声明式扩展点优先（commands/agents/hooks.json 均文件声明；frontmatter 解析器两处同构轻重复换零耦合）；④ 安全立场诚实（审批/Hook/Plan Mode 均标注非真正安全边界）。

**可改进**：`model_pricing` 全局 JSON 字符串宜抽独立数据模型 + 校验；`guard_content` 标记文案写死「MCP 返回」（web 语境不精确，可加 `source` 参数）；readline 历史在 Windows 静默失效（可评估 prompt_toolkit / Python 3.13+ `_pyrepl`）；Hook 事件集不全（缺 `UserPromptSubmit`/`Stop`/`SubagentStop`/`PreCompact`）。 **（2026-09-24 复核：4 项仍开）**——逐条证据（文件与行号）见 §17.4-D，本节不再复制。

**教训**：① EventBus 观察者「同步不得阻塞」决定 Hook 架构——阻断语义只能显式 await，不能 fire-and-forget 观察者；② 幂等/账本链路插新分支必须仍走 `ledger.complete()/fail()` 收尾，否则埋 lease 泄漏；③ 技术债收尾连带修同构兄弟缺口（deferred-work 有 suggested fix 的顺带关闭）。

---

### 十二、周期 10-18 速览（Epic 36-50）

> 2026-09-15 增补（2026-09-24 扩至 Epic 50）：本节收纳 2026-08-24 之后交付的周期。各周期的完整 brief / prd / architecture / epics / stories 在其周期目录内（`_bmad-output/epics/epic-*-周期/`），本节只做**速览 + 契约要点**；口径以 `_bmad-output/sprint-status.yaml` 与 `src/` 代码为准。
>
> **周期 16-18（Epic 48 / 49 / 50）不另设小节**——同一事实已在 §1.3 编号表、§15.1 状态矩阵与 §17.1 当前状态各记一次，此处只留产物地图（2026-09-24 实测）：
>
> - **Epic 48（TCP 网络接口，已删除）** → `epics/epic-48-TCP网络接口周期/`：历史文档完整保留（prd / architecture / epics / sprint-plan + 6 个 story + retrospective），新增 `REMOVAL-NOTICE.md` 记录删除详情（commit `4217b5d`，2026-09-27）
> - **Epic 49（HTTP 网页入口）** → `epics/epic-49-HTTP网页访问周期/`：brief + epics + ARCHITECTURE-SPINE + 6 个 story + 评审产物
> - **Epic 50（网页控制台）** → `epics/epic-50-网页控制台周期/`：brief + epics + ARCHITECTURE-SPINE + 8 个 story（含 2026-09-24 追加的 50-8 体验优化轮）+ 单文件 `reviews.md`（2026-09-26 由 8 份文档合并：规划评审 + 四轮评审 + 三份验收）+ `retrospective-epic-50.md`（2026-09-27 补做）
> - **Epic 51（`/goal` 与 workflow 可信交付优化）** → `epics/epic-51-goal-workflow优化周期/`：brief + ARCHITECTURE-SPINE + epics + 8 个 story + `deferred-work.md`（2026-09-29 建立 → **2026-10-23 收口为 `done`**，deferred「当前活动项无」）
> - **Epic 52（goal 工作流安全并行 Story 执行器）** → `epics/epic-52-安全并行story执行周期/`：brief + ARCHITECTURE-SPINE（AD-16..20）+ epics + 5 个 story + `epic-52-retro-2026-10-09.md`（2026-10-09 交付，5 story 全 `done`，retrospective 已补做）
> - **Epic 53（容器沙箱档）** → `epics/epic-53-容器沙箱档周期/`：brief（D1–D4 冻结决策）+ epics + 3 个 story + `deferred-work.md`（D53-1/D53-2 期二挂起）；镜像构建文件在 `docker/sandbox/Dockerfile`（2026-10-20 立项，3 story **2026-10-24 用户 walkthrough 收口**）
> - **Epic 54（WebSocket 入口）** → `epics/epic-54-WebSocket入口周期/`：brief（D1–D9 冻结决策）+ epics + 4 个 story；实现 `network/ws_protocol.py` / `network/ws_server.py` 与 HTTP/SSE 接线，4 Story done（交付物随 `98ef6d8` 于 2026-10-24 入库并随 0.8.2 发布）+ retro 产物 `epic-54-retro-2026-10-24.md`
> - **Epic 55（CLI 旁路）** → `epics/epic-55-CLI旁路周期/`：brief（回溯补登记，无 story）
> - **Epic 56（WS 对外入口）** → `epics/epic-56-WS对外入口周期/`：brief + epics + phase2-proposal + 8 个 story + 两期 retro
> - **Epic 57（retro 遗留清理）** → `epics/epic-57-retro遗留清理周期/`：epics + 4 个 story（2026-11-02 收口 `done`：7 条 open retro items 全闭环）= 另注：Epic 58（cron 结果推送）与 Epic 59（MEMORY 语义压缩）**未入本总览表**，状态以 `sprint-status.yaml` 为准（2026-11-02 两者均已 `done`）

#### 12.1 周期 10：文件安全与凭证防护（Epic 36-39）· 2026-08-24

> 目录：`epics/epic-36-39-文件安全防护周期/`。交付 4 Epic / 7 story（FR-F1~F5），commit `a1d886d`（25 files，+1881/−44），全量 1135 测试通过。

- **意图**：文件层原本只有「工作区围栏」一个维度；本轮补**凭证路径 deny（读 + 写）**、shell 子进程 **env scrubbing**、`.heagent/` **内部状态读 deny** 三类纵深防御。成果：`file_read(".env")` / `file_write("~/.ssh/id_rsa")` 被拦、`shell("env")` 泄不出 API key。
- **关键决策**：deny 是**与围栏并列的新层**（不并入 `resolve_under_root`，故 git 工具不受影响），顺序固定「先围栏后 deny」，handler 与 policy 两层各自守卫（AD-F1）；规则表为纯函数、**刻意不开用户配置入口**（防无意放宽，AD-F2）；scrub 采「按模式剥离敏感 key」而非白名单透传（AD-F3）；内部状态只 deny 读（AD-F4）。
- **落点**：`tools/path_safety.py`、`tools/sandbox.py`（`scrub_sensitive_env`）、`engine/policy.py`（`_validate_paths` deny 预检）、`tools/builtins/file.py`、`tools/builtins/search.py`、`tools/safety.py`（凭证破坏性命令拦截）。
- **缺口**（2026-09-18 复核）：**凭证 deny 的项目级配置入口已交付**（`.heagent/path_deny.json`，2026-09-17，`63806d3`；仅支持收紧或精确豁免，无整体关闭入口）；仍开——MCP stdio server 子进程的 env scrubbing（与 §17.4-A2 同源；**「cron 子进程」一半不成立**，`cron/` 无子进程路径）、凭证 store 绝对路径读 deny；`shell` 仍可 `cat .env`——deny / scrub **非真正安全边界**（须 OS 级沙箱兜底）。
- **教训**：同一威胁要按它的**所有可达路径**分别封堵——凭证写只拦 `file_write` 会在 shell 的 `rm` / `mv` / 重定向上漏网（36-4 的由来）；补层时做成与既有围栏**并列的独立纯函数层**，才能独立单测/演进且不污染既有调用方。

#### 12.2 周期 11：沙箱会话化（Epic 40）· 2026-08-26

> 目录：`epics/epic-40-沙箱会话化周期/`。交付 4 story（FR-1~4；FR-5 `execute_code` RPC deferred、本周期不建 story），版本 0.4.0，`stories/` 有独立 story 文件。

- **意图**：把 shell 执行从「无状态逐命令透传」升级为 **per-run 会话化**：每 run 有持久 workspace、cwd 跨命令保持、结束 teardown；裁决与执行路径可感知后端强度分级。
- **关键决策**：会话目录根锚定 workspace_root 回退链，经 `RunContext.metadata["sandbox_workspace"]` + contextvar 送达（Firejail 复用既有 `--private` 通道，WinJob 仅作子进程 cwd）；`SandboxTier`（`passthrough < job < firejail < container`）+ `can_relax_approval` 仅 `container` 为真（**弱后端不得降审批**）；env 豁免 `SANDBOX_ENV_ALLOWLIST` 保持 `scrub_sensitive_env` 纯函数；cwd 保持用「`cd` 前缀 + 尾捕获 marker」，用户退出码经 `exit "$__rc"` / Windows marker 回填。
- **配置与可见性**：`SANDBOX_SESSION_WORKSPACE` / `SANDBOX_SESSION_KEEP`（含 CLI/GUI 三态开关）；system prompt `<shell-workspace>` 块**仅在真实后端生效时**注入（诚实门）。
- **缺口**：WinJob 无文件系统/网络隔离、Firejail 非完美边界；目录约定本身非安全边界——须 OS 级沙箱兜底。`deferred-work.md` 的 E40-D1..D4 / C1 全部 Closed。
- **教训**：跨平台 shell 状态保持不能靠猜语义（`%CD%` 在解析期即展开、`pwd` 仅 POSIX）——先写真实 shell 探针再定 marker 形状；同理「有目录」不等于「有隔离」，诚实门比多报一个路径更重要。

#### 12.3 周期 12：目标驱动开发（Epic 41）· 2026-08-29

> 目录：`epics/epic-41-目标驱动开发周期/`。交付 41.1~41.4（FR-1~4），commit `81264bb` / `08a4294` / `2f53406` / `90a8dc4`；2026-09-07 命令族拆为独立模块 `cli_goal.py`（`02f084e`）。

- **意图**：给交互 CLI 补 BMad 式目标驱动入口——`/goal <描述>` 一条命令启动 skill、逐 story 独立会话推进、进度落盘可续跑、`/goal auto` 无人值守。
- **关键决策（分层铁律 NFR-1）**：**方法论只存在 `.heagent/skills/goal/SKILL.md`（人可直接编辑），机制全落 `cli.py`（约 130 行）**，明令禁止 `goal.py` / Pydantic `GoalState` / runs.jsonl；**会话边界 = story 边界**（每步全新 SubAgent + skill 正文路径直读 + `WindowResetConfig` 阈值清窗续跑）；机器只扫三个标记（`status:` / checkbox 计数 / `> in-progress: S<n>`）；`auto` 经 `JobStore` 注册 `goal-advance <goal_id>`，`_run_job` 前缀分流到同一推进路径，done/blocked 自动注销。
- **观测（FR-3）**：`SubAgent(metadata=...)` 透传 `goal_id` / `goal_kind` 进 `.heagent/runs/<run_id>.json`，保留键过滤、`kind=subagent`；默认 None 行为逐字节不变。
- **缺口**（2026-09-18 复核）：**两项均已闭合**——GUI `/goal` 收口（stderr→RichLog、Esc 取消、GUI 持有 `CronScheduler`、pilot 交互测试）由 E41-D7 于 2026-09-17 完成（`44ab001`）；goal 跨进程锁由 E41-D5 于 2026-09-17 完成（`persist.file_lock` + `_goal_mutex`，`855d135`）。本周期无未闭合项。
- **教训**：把「方法论当文本、机制当薄代码」切开后工作流演进只改 skill 文件——但边界判定一旦交给 LLM 写盘，就必须给每个「没落盘 / 白跑 / 触顶」配**显性报错**，否则失败会长得像成功。

#### 12.4 周期 13：BMad 技能包运行时（Epic 42）· 2026-09-01

> 目录：`epics/epic-42-BMad技能包运行时周期/`。交付 42-1~42-5（FR1~FR8），commit `6168100`（8 files，+580/−1）。

- **意图**：把技能从「单个 `SKILL.md` 学习型技能」升级为**可安装、可验证的声明式技能包运行时**——`he-*` canonical ID + `bmad-*` 兼容别名、按需安全读取 step/references/templates/assets/scripts、不自动跳步的可恢复单步执行。
- **关键决策**：五对象单一职责分层（`SkillPackage` / `SkillCatalog` / `SkillResolver` / `SkillRunner` / `SkillImporter`，落点 `memory/skill_packages.py`、`memory/skill_importer.py`）；路径围栏复用 `tools/path_safety.resolve_under_root` 而**刻意不接** `check_read_denied`（避免内部状态读限误伤本地技能目录）；导入锁走 `engine/persist.atomic_write_text` 原子写 + SHA-256 入口哈希 + `.heagent/skills/manifest.lock`；冲突不静默（多候选 / 缺 `SKILL.md` / 源缺失均返回带 ID 与路径的诊断错误）。
- **缺口**：资源读取竞态（`resolve`→`read` 之间的替换窗口）**不在本周期交付**，显式转出为独立 story → 由 Epic 46.1 评估、46.2 以 `O_NOFOLLOW` 加固最终组件；中间目录替换、可信导入 snapshot、OS sandbox 仍 backlog。命名后演进：角色技能 canonical 于 `6b044af`（2026-09-07）迁至 `bmad-agent-*`，`he-*` 降为 legacy 别名。
- **教训**：「解析后校验 → 真的读」不是原子动作——分层的路径围栏只能说 defense-in-depth，**围栏与真边界必须在文档里写清区别**，并把竞态窗口显式转成独立 story 而不是默认已解决。

#### 12.5 周期 14：目标级工作流（Epic 43-46）· 2026-09-01

> 目录：`epics/epic-43-46-目标级工作流周期/`。交付 4 Epic / 11 story（FR1~FR5）；核心 commit `2e6c7e9`（编排原语）、`b7a4784`（Epic 43 checkpoint）、`a6e48f0`（Epic 44 rollover）、`63f1c78`（pause/resume）、`840731c`（workflow audit）、`44a77e4`（质量门收口）、`ab18d19`+`c7349a5`（TOCTOU 评估）、`9115a25`（`O_NOFOLLOW` 加固）。

- **意图**：把 `/goal` 从「单次会话推进」升级为**可控、可恢复、可审计**的长期执行（确定性阶段路由 + 人工闸门 + checkpoint/暂停恢复 + 跨上下文 Token 分段 rollover + 目标级运维与质量门）；Epic 46 与主线正交，只评估技能资源并发替换风险。
- **关键决策**：路由 / 迁移 / 阈值 / 幂等**一律由确定性代码裁决**，LLM 不得决定阶段或伪造完成（落点 `engine/workflow.py`：`GoalWorkflowState` / `WorkflowCheckpointStore`——`WorkflowOrchestrator` / `TokenBudgetManager` / `RolloverCoordinator` / `RecoveryEnvelope` 为交付时形态，已随 2026-09-17 legacy 相位机删除 `d835bd8`）；**所有权切分**——`GOAL.md` 拥有 Goal/Story 看板，`workflow.json` + `checkpoints/` 只存阶段/技能/step/Token 与恢复元数据、不复制 checkbox；checkpoint **仅在工具事务结束后**原子写入（在途工具绝不标成功，同 run/step 重复提交幂等、内容冲突显式失败、损坏状态进 `blocked`/`failed`）；rollover 固定「checkpoint → reset → fresh run」；质量门单一入口 `scripts/quality_gate.py`（goal smoke → 回归+覆盖率≥87 → ruff check → ruff format → mypy，fail-fast）+ CI 无凭据 `goal-smoke` job。
- **Epic 46（评估先行）**：加固只落在 `memory/skill_packages.py`——统一「`resolve_under_root` 解析 → `os.open`（支持平台附 `O_NOFOLLOW`）→ `fstat` 常规文件校验 → descriptor 读取」，`path_safety` 围栏不动，不支持平台保留兼容回退。
- **缺口**（2026-09-18 复核）：Epic 46 后续 backlog **仍开**（descriptor-relative open / 目录句柄、可信导入 snapshot、OS sandbox → §17.4-A1）；**legacy 相位机已于 2026-09-17 删除**（`d835bd8`），`engine/workflow.py` 仅存 `GoalWorkflowState` / `WorkflowCheckpointStore`（新目标能力应扩展 `engine/workflow_runner.py`）；45-1/45-2 **确认仍无 story 文件**（该 epic 下只有 `45-3`），spec-45-3 与 spec-46-1 已在归档提交中删除或改名（仅存 git 历史）。
- **教训**：「状态所有权」与「事务结束才 checkpoint」必须先钉死，否则恢复语义会退化成重复完成；用户态路径检查永远不是安全边界——**评估先行、加固只做最终组件**，残余竞态写进文档而不是宣称已修。

#### 12.6 周期 15：声明式 BMad 敏捷工作流（Epic 47）· 2026-09-01 → 2026-09-15

> 目录：`epics/epic-47-声明式BMad敏捷工作流周期/`。交付 47-1~47-10（含 47-8~10 批次并行）；核心 commit `b49ff78`（工作流契约中文化并吸收 bmad-build 方法论）、`f0d7837`（角色与模板契约重构）、`94d4c36`（同 Epic Story 并行）、`cc8cb3f` + `95ae3e6`（在途续租 / 运行时治理）、`5f6c781`（deferred 台账按 epic 归档）。

- **意图**：把 `/goal` 从 Goal→Story 轻量循环升级为 **Goal→Epic→Story 的 BMad 敏捷流程**——工作流规则、阶段顺序、产物契约由 Markdown 声明（`.heagent/workflows/workflow.md` + 角色 `SKILL.md`），通用 Runner 只负责解释执行；PM/Analyst/Architect/UX/Dev 以可改的本地 Agent 技能包提供。
- **关键决策（Agile Contract）**：**方法论归 Markdown、确定性边界归代码**（步骤顺序 / 输入输出 / `validation` / checkpoint / 恢复 / 错误态不可交给 LLM）；`GOAL.md` 只管 Epic 看板、`sprint-status.yaml` 是 Epic/Story 状态**唯一写目标**；一个 Story 一个执行会话（WIP=1）、Review 失败退回实现、Epic 完成后 Retrospective；产物缺失 / 格式非法 / 验收失败 / 冲突 / 人工 checkpoint **必须显式停止**。
- **落点**：`engine/workflow_runner.py`（单步推进 / story loop / resume / gate 不绕过）、`engine/artifacts.py`（frontmatter + 固定章节 + Given-When-Then + TBD 拒收 + 层级 ID 校验）（review / retrospective / correct-course 曾落 `engine/agile.py`，该文件已于 2026-09-03 删除 `f49c20a`）、`memory/skill_packages.py`（复用根目录围栏读资源）、`cli_goal.py`（装配 + `_goal_auto_lock`）。
- **缺口**（2026-09-18 复核）：**E47-D1**「ledger 记录在途被删」已修复（在途每 40s 续租 + 回写失败只告警不吞结果 + 区分「不存在 / 损坏」）；**施动者未唯一归因仍开**（残余风险 LOW，契约写入 `tool_execution.py` 模块 docstring）；`skill_update` 遇富正文技能拒绝改写（须先备份）**仍开**；**bmad-build Step 07 迭代预算已于 2026-09-17 闭合**（`.heagent/skills/he-goal/workflow.md:208` 声明 `max_iterations: 100`，`d7dc758`；E41-D6）。
- **教训**：「流程方法论 → Markdown，确定性规则 → 代码」必须分离到底——一旦把流程分支写回 CLI，声明式契约就开始漂移，checkpoint 与产物校验会失去单一可信源。

### 十三、补丁 spec 归档与技术债

> **2026-09-15 重组**：原 `patches/`（按领域分子目录 provider/context/memory/cron/mcp/sandbox/_meta）**已解散**——计划外补丁 spec 按**归属 epic** 归档进 `epics/<周期>/<epic-NN-主题>/`（与它服务的 epic/story 同目录，逐文件映射见 `README.md`「补丁 spec」节；spec 不占 Epic 编号，故不进编号序列），不再单独成目录；`specs/` 为 quick-dev 本地工作件（gitignored）。**遗留项**：未闭合项在 `implementation-artifacts/deferred-work-archive.md`；已闭合项按归属 epic 归档到各周期 `deferred-work.md`（2026-09-15 整理，原 `patches/_meta/deferred-work.md` 全部条目闭合后随目录一并退役删除）。

#### 13.1 已闭合技术债（按归属 epic 归档，2026-09-15）

> **2026-09-22 增补**：架构优化周期（Phase 0–5，非 BMad 流程）的 spec 已改名归档至 `implementation-artifacts/arch-optimization-cycle/`（总方案 + phase0..5，各含执行记录；原 `docs/test.md` 删除、内容全部并入）。

原跨周期台账 `_bmad-output/patches/_meta/deferred-work.md`（2026-09-15 退役并删除）的条目**已全部闭合**，按归属 epic 归并进各周期 `deferred-work.md`（原始长文历史不再保留）。**活动（未闭合）项**仍在 `implementation-artifacts/deferred-work-archive.md`。**2026-09-24 补**：该台账归档区里 5 条**有归属 epic** 的条目（Z-D10 / Z-D11 / Z-D13~Z-D15）已按同一规则回填到各自周期 `deferred-work.md`，台账只留 ID 索引（跨文档 `Z-Dn` 引用不受影响）。

| 归档文件 | 条目（ID） | 要点 |
|----------|-----------|------|
| `epics/epic-01-10-主线规划周期/deferred-work.md` | E1-D1/D2、E4-D1/D2、E5-D1、E10-D1/D2 | ProviderChain 双层重包 + 流式 backstop 对称化；Dreaming AC6 `web_fetch` 接 `guard_content`（Epic 35）+ 3 个 LOW（抽 `cron/expr.py` 纯叶子 / 孤儿 task 取回 / 取消语义区分）；`SkillStore` 写竞态**核实不成立**；cron 关停硬上界 + cron expr 诊断 |
| `epics/epic-11-18-MCP集成周期/deferred-work.md` | E11-D1、E11-D2、E11-D3 | FR-3 评审 6 项（4 修 / 2 决策关闭）；DP-4 返回内容启发式围栏**已交付**；注入签名 global/home 级**决策关闭（won't do）** |
| `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md` | S-D1..D6 | engine sandbox 后端评审 4 项（含进程组 kill **勘误：早已交付**）；取消信号保留（`suppress` 语义勘误）；reap 鲁棒性 3 项；**S-D4..D6（2026-09-17 优化批次 2）**：资源限额（`SANDBOX_MEMORY_LIMIT_MB`/`SANDBOX_CPU_SECONDS`）/ 高级参数（`SANDBOX_PROFILES` 声明 --seccomp/--caps）/ per-tool 粒度（`SANDBOX_TOOL_PROFILES`），均默认关闭 |
| `epics/epic-36-39-文件安全防护周期/deferred-work.md` | F-D1 | **（2026-09-17 优化批次 2）**凭证 deny 项目级可配置入口 `.heagent/path_deny.json`（收紧或放行显式列举项，无整体关闭入口；含函数名勘误） |
| `epics/epic-40-沙箱会话化周期/deferred-work.md` | E40-D1..D4、E40-C1 | 孤儿目录 GC / 目录对模型可见 / WinJob cwd 可测缝 / CLI 平权 |
| `epics/epic-41-目标驱动开发周期/deferred-work.md` | E41-D1..D7（**全部闭合**） | goal 会话预算 / TUI 路由 / REPL 异常围栏 / role metadata 生命周期；**E41-D5（2026-09-17 优化批次 4，`855d135`）**：goal 跨进程锁（`persist.file_lock` + `_goal_mutex`）；**E41-D6/D7（2026-09-17 优化批次 1）**：Step 07 迭代预算（`max_iterations: 100`）/ GUI `/goal` 收口（stderr→RichLog、Esc 取消、GUI 持有 CronScheduler） |
| `epics/epic-47-声明式BMad敏捷工作流周期/deferred-work.md` | E47-D1 | ledger 记录在途被删（在途续租 + 回写容错 + 可诊断性）——engine 运行时治理增量 |
| `implementation-artifacts/deferred-work-archive.md` | Z-D1~Z-D9、Z-D12（**正文**）+ Z-D10/Z-D11/Z-D13~Z-D15（**仅 ID 索引**） | 勘察类闭合归档正文：**09-17 批次** dream 反向边消除 / frontmatter 六处解析器收敛 / provider 骨架**不收敛**（护栏钉死）/ JsonlSink 保持现状 / cron store to_thread / 拦截日志 / 三死字段清理；**09-18** 角色死字段删除 / 沙箱进程数限额 + WinJob 常量修正；**09-23** MEMORY.md 非 UTF-8（fail-soft） |
| `epics/epic-48-TCP网络接口周期/deferred-work.md` | Z-D10、Z-D11 | **（2026-09-24 回填）**Story 48-5 评审 C-1 / C-2：运行栈日志的观测故障免疫（`safe_log` + 进程级 `install_logging_fault_guard`）/ 日志行的凭证脱敏（`LoggingObserver` 掩码） |
| `epics/epic-50-网页控制台周期/deferred-work.md` | Z-D13~Z-D15 | **（2026-09-24 回填）**Story 50-5 / 50-6 派生：资源旋钮 21 键上界 / 审计行数上限（行级裁剪 500 条）/ 首页遮罩 `[hidden]` 守卫 |

#### 13.2 补丁 spec 清单（已交付，按主题分组）

> **2026-09-15 重组**：`patches/` 目录已解散，下列 spec 均已按**归属 epic** 归档（逐文件映射见 `README.md`「补丁 spec」节）。本小节保留交付内容记录，文件名后不再附路径。

**P0 Provider 加固**：`p0-provider-hardening.md`（done，2026-06-19）——`wrap_provider_error` 共享函数，openai/anthropic/chain 源头包装 SDK 异常，打通密钥轮换/重试/异常层级三连；评审发现 `_classify` 缺 `"timed out"`/`"connection"` 关键词已 patch。`p0-hardening-review-diff.txt`（2026-09-15 已删除）为评审补丁文本。

**Story 补丁**：`3-3-token-counter.md`（done；文件 2026-09-15 已删除）——`context/tokens.py` CJK 感知启发式估算（纯 Python 无 tiktoken）；`5-1-subagent-context-injection.md`（done，2026-06-17）——SubAgent 继承 soul/skills/facts/profile/compressor/context_dir 六参数；`epic-5-context.md`（规划编译件）——FR-16/17 的拆分决策。

**MCP 补丁**：`fr3-mcp-auto-unregister.md`（done，2026-07-01）——`_watch` 周期 `send_ping` 健康探测，失败即注销；`spec-dp4-mcp-safety-guard.md`（done，2026-07-08）——SafetyGuard 执行前工具名黑名单拦截（`blocked_tools` 正则 + `safety_blocked_tools` 配置）；`spec-dp4-mcp-result-guard.md`（done，2026-07-10）——`mapping.bridge_result` 内置 10 条注入签名启发式扫描 + 标记透传（不阻断不截断）。

**sandbox 健壮性系列（2026-07-09~10）**：`spec-engine-sandbox-backend.md`（done）——`CommandRunner` Protocol + `PassthroughRunner` + `FirejailBackend` + RuntimeSlot 注入；`spec-sandbox-timeout-validation.md`（done）——timeout 正整数校验（fail-closed 拦 None/str/float/bool/nan/inf）；`spec-sandbox-cancel-signal-preservation.md`（done）——取消信号保留（`suppress(BaseException)` + 裸 raise）；`spec-sandbox-reap-robustness.md`（done）——reap 保护 + `_REAP_WAIT_TIMEOUT=5.0` + kill/wait 解耦。

**关停硬上界三件套（同构，统一 5.0s）**：`spec-mcp-shutdown-timeout.md`（done，2026-07-10）——`_await_shutdown` 两轮；`spec-cron-stop-timeout.md`（done，2026-07-11）——`_await_stop` 单轮；`spec-deferred-low-cleanup.md`（done，2026-07-11；2026-09-15 删除——条目已被 `epic-11-18`/`epic-S1-S4` 的 `deferred-work.md` 更详覆盖）——deferred LOW 收尾 + 测试保真度补齐。

**Dreaming / steering（2026-08）**：`spec-dreaming-memory-consolidation.md`（冻结 spec，2026-08-11）——`memory/dream.py` `DreamScheduler`（双触发 cron `0 3 * * *` + idle 30min；`dream_enabled` 默认 False opt-in）+ `engine/roles.py` dreamer RoleSpec（白名单 fact_add/profile_update/skill_*/web_fetch，黑名单 shell/file_write/cron_*/task_*/git_*；**不持 `file_read`** 最小权限）+ `dream_max_iterations` 默认 20；`spec-dreaming-defer-cleanup.md`（done，2026-08-12）——3 个 LOW defer 收口（抽 `cron/expr.py` 纯叶子）；`spec-steering-followup.md`（spec，source 2026-08-10）——`AgentLoop` 双层循环（外层 follow-up + 内层 steering），两个可选 async callback，`run()`/`run_stream()` 提取共用 `_run_loop` 模板方法；`spec-business-data-integration.md`（母规划 spec，2026-08-11；**文件 2026-09-15 已删除**——未启动、未衍生实现 spec 或 epic，正文仅存 git 历史，见 `_bmad-output/README.md`「已失效删除」）——业务运营数据整合，**混合以 MCP 为主**，5 阶段（盘点/只读 MVP/写操作审批/跨系统编排/安全硬化），治理核心依据 = 内置 `@tool` annotations 在 PolicyEngine 阶段不被消费 vs MCP 工具闸门有效；`spec-mcp-user-injection-signatures.md`（**项目级已交付**，2026-07-27~31）——用户可配置注入签名入口 `.heagent/injection_signatures.json`（workspace 围栏 + 进程级懒加载 + 畸形条目 fail-safe）；**全局/home 级入口 2026-09-15 决策关闭（won't do）**：MCP 非必要方向 + home 级会跨项目静默生效，见 `epic-11-18-MCP集成周期/deferred-work.md` E11-D3。

**其他**：`cli-status-bar.md`（done，2026-07-23）——交互模式提示符显示模型 + token 用量（`_format_status`）；`code-review-2026-07-20.md`（审查报告；2026-09-15 已删除）——727/727 通过，无 🔴 P0 当前缺陷，P0-3 已修复验证、P1-1~P1-3 与 P2-1~P2-5 记录；`retrospective-engine-p5.md`（done，2026-06-29）——P5-3/4/5 交付 + P5-1/2 反转 deferred（后 2026-07-21 交付）；`retrospective-p0-tech-debt.md`（done，2026-06-29）——三条全部关闭。

#### 13.3 specs/（quick-dev 本地工作件）

- `spec-dreaming-memory-consolidation.md`（冻结实现版，done，2026-08-11）——与 patches 详版同一 spec 的冻结版，含 AC6 降级 Change Log（web_fetch 未接 guard_content → 函数级复用）。
- `spec-sandbox-backend/SPEC.md`（P0-a 契约 spec）——把「缺后端」从静默成功改成**显性失败**（fail-closed）：`SANDBOX_REQUIRED` 且无后端 → 拒绝执行返回 `is_error=True` 点名缺失 profile，**绝不静默回退裸 handler**；CAP-1~3 + Constraints（fail-closed 默认路径 Windows/Linux 均可跑）。
- `spec-sandbox-backend/stack.md`（P0-a companion）——`SandboxBackend Protocol`（`profile: str` + `async def run(call, handler)`）+ `SandboxRegistry`（profile 名 → backend）+ 4 条不变量（无后端→is_error+handler 未调 / 后端在→backend.run 被调 / DIRECT 不受影响 / subclass 完整覆写不被劫持）。

---

### 十四、engine/ 增量（epic 外 P 批）

运行时治理层（`PolicyEngine` + `ToolExecutor` + `store/ledger/observability`）按 P 批演进，不挂 Epic 编号，进度记入 `frame.md` 4.12：

| 批次 | 内容 |
|------|------|
| P0 | loop engine runtime 落地（`EngineContainer` 注入 `AgentLoop`） |
| P1/P2 | 多 agent 角色化 + supervisor 编排（`engine/roles.py`） |
| P3/P4 | checkpoint-resume + 工具执行幂等（store/ledger） |
| P5-3/4/5 | 结构化子任务结果（`SubTaskOutcome`）+ `parent_run_id` 树形聚合 + resume 流式版 |
| P5-1/P5-2 | schema 级工具白名单过滤（`AgentLoop._get_tools()`）+ `SubAgent` 可选 `window_reset`（2026-07-21 交付） |
| sandbox 后端 | `execute_in_sandbox` 接 `CommandRunner` 抽象（`tools/sandbox.py`）：默认 Passthrough，可注入 `FirejailBackend`（Linux）/ `WinJobBackend`（Windows），经 `RuntimeSlot` 注入 |

**工具执行链（冻结）**：`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。

**engine 承重设计**：`PolicyEngine` 产出 `PolicyVerdict`（mode ∈ {DIRECT, APPROVAL_REQUIRED, SANDBOX_REQUIRED, BLOCKED}）；`ExecutionLedger` 缓存命中仍须复核最新 policy；lease-active 命中跳过重复执行；`pub/persist.py` 原子写 + 损坏 JSON 容错 + 可选跨进程文件锁；`observability.py` EventBus 派发引擎事件。

---

### 十五、统一编号体系与状态矩阵

#### 15.1 Epic 状态矩阵（权威 = `_bmad-output/sprint-status.yaml`，2026-09-24 复核）

| Epic | 主题 | Stories | 状态 |
|------|------|---------|------|
| 1-10 | 主线 MVP + 自学习闭环 | 37 | 全部 done |
| 11 | MCP 工具桥接 | 5 | done |
| 12 | GitHub 只读验收 | 1 | done |
| 13 | 安全边界与开源可用 | 2 | done |
| 14 | MCP v1→v2 升级准备 | 3 | done |
| 15 | 写操作治理（FR-A） | 4 | done |
| 16 | Resources on-demand（FR-B） | 4 | done |
| 17 | Prompts CLI slash（FR-C） | 4 | done |
| 18 | 内置工具扩展（git + path safety） | 4 | done |
| S1-S4 | Sandbox 硬化 | 8（S4-1 skipped） | done |
| 19 | 健壮性硬化（FR-A1~A5） | 4 | done |
| 20 | 质量工程化（FR-C1~C6） | 5 | done |
| 21-24 | 质量工程深化（FR-Q） | 18 | done |
| 25-28 | GUI 终端界面（FR-G） | 12 | done（retrospective optional） |
| 29-35 | 交互与可扩展层（FR-A~G） | 27 | done（2026-08-19；无独立 story 文件，quick-dev 执行） |
| 36-39 | 文件安全与凭证防护（FR-F） | 7 | done（2026-08-24；retrospective optional） |
| 40 | 沙箱会话化执行（FR-1~4；FR-5 deferred） | 4 | done（2026-08-26；retrospective optional） |
| 41 | 目标驱动开发 / `/goal`（FR-1~4） | 4 | done（2026-08-29；retrospective optional） |
| 42 | BMad 技能包运行时（FR1~FR8） | 5 | done（2026-09-01；retrospective optional） |
| 43-46 | 目标级工作流（编排 / 分段 / 运维收口 / TOCTOU 评估） | 11 | done（2026-09-01；retrospective optional） |
| 47 | 声明式 BMad 敏捷工作流（含 47-8~10 批次并行） | 10 | done（2026-09-01 → 09-15；retrospective done） |
| 48 | TCP 网络接口（JSON Lines / 单请求单响应 / localhost） | 6 | done（2026-09-22 建立并交付；retrospective 2026-09-23 补做） |
| 49 | HTTP 网页入口（自启动 + SSE + 同源防线 + 静态白名单） | 6 | done（2026-09-23；retrospective optional） |
| 50 | 网页控制台（工作区一等化 / 项目注册表 / 会话 API / 配置四层来源与写入通道 / 两栏 UI） | 8 | **done**（8 story 均 `done`，2026-09-27 收口；四轮收口评审已出并放行，retrospective 已补做） |
| 51 | `/goal` 与 workflow 可信交付优化（预检/状态视图 / 事件转换 / 结构化证据 / 真实 Gate / 审批 / 模板冻结 / GoalScript / 安全并行） | 8 | **done**（8 story 全部 `done`，2026-10-23 收口；A25–A28/A33/A37–A39 全部闭合归档；retrospective `optional` 未补做） |
| 52 | goal 工作流安全并行 Story 执行器（声明门控批次 / 写集围栏 / 宿主 Git 审计 + 撤销闩） | 5 | done（2026-10-09 交付并通过四层评审；retrospective 已补做） |
| 53 | 容器沙箱档（`DockerRunner` + 镜像 pin + 网络档 + 显性降级留痕；期二 MCP stdio / 审批降级挂 deferred） | 3 | **done**（3 story done，**2026-10-24 用户 walkthrough 收口**；期二挂 D53-1/D53-2） |
| 54 | WebSocket 入口（单 run 订阅 / 游标续传 / cancel·ping / Origin 防线 / per-run 限额；无认证无 TLS） | 4 | **done**（2026-10-24 收口纠正：交付物随 `98ef6d8` 入库并随 0.8.2 发布；retro 产物在周期目录） |
| 55 | CLI 旁路（`/api/cli/ws` 终端直订，只挂本地 listener） | 0 | **done**（回溯登记无 story 行；随 `98ef6d8` 入库并随 0.8.2 发布） |
| 56 | WS 对外入口（强制 Bearer token / 可选 TLS / 双 listener 并存 / 端点可见性） | 8 | **done**（期一 4 + 期二 4，均 2026-10-24 交付；两期 retro 各一份） |
| 57 | retro 遗留清理（清空 7 条 open retro action items） | 4 | **in-progress**（2026-10-26 立项，57-1..57-4 当日全 done，epic 收口在途） |

> **retrospective 补做**：36/37/40/41/42（2026-09-18，`d4b0387`）、Epic 48（09-23）、Epic 50（09-27，键值随之改 `done`）；36/37/40/41/42 键值已于 2026-10-27 归一 `done`。实测仍为 `optional` 的 epic 共 **14 个**（2026-10-27：25-28 / 38-39 / 43-46 / 49 / 51 / 55 / 57，均未补做），清单见 §17.4-C；Epic 54 / 56 retro 产物在各周期目录。

**Story 文件归档**：路径形如 `epics/<周期>/epic-NN-<主题>/stories/` 或周期级 `epics/<周期>/stories/`——**35 个目录 / 134 个 story 文件**（2026-10-27 实测）。建有 `stories/` 的：`epic-01/05/14/15/16/19`、`epic-25~28`、`epic-36~40`、`epic-42`、`epic-43~48`、`epic-49/50`、`epic-51~54`、`epic-56/57`（40/42/49/50/51~54/56/57 为周期级）、`epic-S1~S4`；其余 epic 仅登记于 sprint-status。6 个 36-39 story 文件 frontmatter 仍写 `status: backlog`（sprint-status 早已 `done`），见 §17.4-C。`review` / `in-progress` story 现为 **0 条**（53-1~53-3 已随 2026-10-24 walkthrough 转 done）。

**跨周期 Action Items（3 条全部 closed）**：Epic 13 FR-3 auto-unregister（2026-07-01，commit 3203e4a）；DP-4 第一半 SafetyGuard 执行前拦截（2026-07-08）；DP-4 第二半 MCP 返回内容围栏（2026-07-10）。

#### 15.2 FR 编号空间对照（引用须写全限定）

| 周期 | 编号 | 数量 | 状态 |
|------|------|------|------|
| baseline | FR-1~24 | 24 | 全部实现 |
| mcp（阶段一） | FR-1~11 + NFR-1~7 | 11 | 全部实现 |
| mcp（阶段二） | FR-1~5 + NFR-1~6 | 5 | 全部实现（含 POC 验证） |
| mcp（阶段三） | FR-A1~A7 / FR-B1~B4 / FR-C1~C4 + NFR-1~7 | 15 | 全部实现 |
| sandbox-hardening | FR-S1~S7 + NFR-S1~S6 | 7 | 全部实现（S4-1 emit 事件 skipped） |
| robustness-hardening | FR-A1~A5 + FR-C1~C6 + NFR-1~4 | 11 | 全部实现 |
| quality-engineering | FR-Q1~Q20 + NFR-Q1~Q4 | 20 | 全部实现 |
| gui | FR-G1~G24 + NFR-G1~G8 | 24 | 全部实现 |
| interaction | FR-A1~A5 / FR-B1~B3 / FR-C1~C4 / FR-D1~D4 / FR-E1~E4 / FR-F1~F4 / FR-G1~G4 | 28 | 全部实现 |
| file-safety-hardening（Epic 36-39） | FR-F1~F5 + NFR-F1~F5 | 5 | 全部实现（2026-08-24） |
| sandbox-session（Epic 40） | FR-1~4 + NFR-1~4 | 4 | 全部实现（FR-5 `execute_code` RPC deferred） |
| goal-driven（Epic 41） | FR-1~4 | 4 | 全部实现（2026-08-29） |
| skill-package（Epic 42） | FR1~FR8 + NFR1~NFR6 | 8 | 全部实现（2026-09-01） |
| goal-workflow（Epic 43-46） | FR1~FR5 | 5 | 全部实现（Epic 46 后续 backlog 见 17.3） |
| declarative-workflow（Epic 47） | 无 FR 编号（Agile Contract + 47-1~47-10） | — | 全部实现（2026-09-15） |
| 网络入口（Epic 48-50） | 无 FR 编号（story 级需求，走 sprint-status） | — | 48 已删除（2026-09-27）；49 已交付；50 已收口（2026-09-27，8 story `done`） |
| **合计** | | **~171 FR** | |

#### 15.3 关键 deferred 决策锚点

> 本节原列 3 个常被跨文档引用的锚点（`DP-4` / `P5-1`·`P5-2` / `E4-D1` Dreaming AC6），其状态与证据已分别在 **13.1**（E11-D3、E4-D1 两行）、**13.2**（MCP 补丁段）与**十四**（P5-1/P5-2 行）逐条登记——**同一状态写两处必然漂移，故此处不再复制**。跨文档引用时请写全限定编号（如 `DP-4` 第二半 / `E11-D3` / `E4-D1`）。

---

### 十六、跨周期模式：做对 / 可改进 / 教训

#### 16.1 做对了什么（12 条跨周期模式）

| # | 模式 | 证据 |
|---|------|------|
| 1 | **协议优于实现** | BaseProvider Protocol、@tool 装饰器、Middleware 管道——新增模块零改动核心 |
| 2 | **deferred 编号化** | DP-4 等「暂不做」决定跨文档引用（CLAUDE.md/frame.md/architecture.md），防遗忘 |
| 3 | **「不成立」关闭模式** | SubAgent 竞态误判经核实关闭 + 回归测试锁定假阴性——比硬修不存在的问题更有价值 |
| 4 | **依赖最小化** | 手写 cron 解析器避掉 croniter、文件锁全 stdlib——NFR 贯彻始终 |
| 5 | **增量保持干净** | P5+engine 叠加式不动契约、DI 注入不篡改 AgentLoop 签名 |
| 6 | **YAGNI 克制** | MCP 2 transport 不抽 Protocol、不新建异常/重试、annotations 透传不裁决 |
| 7 | **防御纵深意识** | 所有安全相关组件明确标注「非真正边界，须 OS 级沙箱兜底」 |
| 8 | **分层门禁** | 本地 88/CI 90 coverage、bandit -ll 不阻塞 CI——差异化约束不互锁 |
| 9 | **优雅降级模式** | Firejail/WinJobBackend 不可用 → warn + Passthrough，不 crash、不中断 |
| 10 | **对称性审查** | send/stream、enter/exit、kill/wait——成对路径互相对照补齐 |
| 11 | **方法论与机制分离** | `/goal` 工作流：流程规则归 Markdown（`.heagent/skills/he-goal/workflow.md` + 角色 SKILL.md，人可直接改），确定性边界归代码——工作流演进零代码改动 |
| 12 | **诚实门（honest gate）** | 能力「未真正生效」时宁可不报：`<shell-workspace>` 仅在真实后端就绪时注入；围栏 / 沙箱一律标注 defense-in-depth，不制造「已安全」假象 |

#### 16.2 可改进什么（10 条，2026-09-24 复核）

> 下表只留**模式 + 结论**，标注**仍开 / 部分解决 / 已修复 / 已裁定接受**；逐条证据、行号与完整待办清单一律见 **§17.4**（本节不复制，避免两处漂移）。

| # | 模式 | 现状与建议 |
|---|------|-----------|
| 1 | 安全边界诚实度 | **长期基调（非待办）**：SafetyGuard/engine sandbox 均非真边界但命名像边界——命名/文档应持续降低「安全」期望，各文档已统一标注 defense-in-depth |
| 2 | 回顾不及时 | **部分改善**：retrospective 仍 `optional` 的 epic 共 **14 个**（2026-10-27 实测：25-28 / 38-39 / 43-46 / 49 / 51 / 55 / 57，均未补做；36/37/40/41/42、48、50 已补做）——清单见 §17.4-C |
| 3 | 静默降级 | **仍开**：firejail / WinJob 不可用仅 `logger.warning` + 降级 Passthrough，无 CLI banner 或首次加载提示——落点见 §17.4-D（原此处引的 `tools/sandbox.py:423` 已随该模块包化失效） |
| 4 | 编号冲突 | 两份 Epic 14 同名异义已 2026-07-23 统一——编号空间现无冲突 |
| 5 | 复杂度接受 | **已裁定接受**：`agent/loop.py` 的 `run_stream` 仍以 `noqa: C901` 放行（抽函数后实测仍 17 > 15，依据写入 docstring）——证据见 §17.4-B8，不再作为待拆分项 |
| 6 | 可观测缺口 | **仍开**：S4-1 emit 事件仍 `skipped` + benchmark 数据仅 CI artifact（7 天过期、不入库）——两条分别见 §17.4-C / §17.4-D |
| 7 | 内置预设缺失 | **部分解决**：`SANDBOX_PROFILES`（2026-09-17）已可声明 `--seccomp`/`--caps` 等参数，但无开箱即用预设库；cron 亦无常见模板——见 §17.4-D |
| 8 | 扩展点不足 | **部分解决**：`slash.py` 已是注册表驱动的斜杠命令层，但 CLI 入口仍是最小 `startswith("/")` 分发、MCP prompts 的「结构化注册表」仍是候选——落点与行号见 §17.4-D |
| 9 | 规划产物滞后于交付 | **仍开**（2026-09-24 复核）：6 个 36-39 story 的 frontmatter 仍为 `backlog`、45-1/45-2 无 story 文件——逐条见 §17.4-C |
| 10 | 跨进程互斥缺位 | **已修复**（2026-09-17）：goal 指针 / `GOAL.md` 跨进程 `file_lock`（E41-D5）；在途记录续租（E47-D1）同源问题一并闭合——剩余仅「施动者未唯一归因」（LOW，见 §17.4-B6） |

#### 16.3 迭代教训（12 条，详见 iteration.md 三）

1. edge case hunter 会误判并发竞态——先核实是否真有 `await` 交错再定级。
2. 异常包装要加守卫避免双层重包（`_raise_provider_error`）。
3. 流式与同步路径要对称（send/stream backstop）。
4. 安全边界必须诚实声明，不制造「更安全」假象。
5. 两种模式并存要标记冲突而非折中（工作区路径围栏已收敛为 `resolve_under_root`）。
6. 评估结论要留依据（P5-1/2 反转的取舍依据）。
7. 缓存命中仍须复核策略裁决（ledger 缓存 vs policy）。
8. 关停/清理路径必须有硬上界（sandbox/MCP/cron 三处同构 5.0s）。
9. 上下文切分要保证消息配对完整（compressor 孤儿 TOOL 消息）。
10. 跨 task session 泄露要两面收尸（`_server_loop` except + finally 双清理）。
11. 恢复语义取决于「状态所有权 + 事务结束才 checkpoint」——先钉死这两条，否则恢复会退化成重复完成。
12. 竞态与围栏必须诚实分级：显式把窗口转成独立 story（Epic 42→46）、加固只做最终组件，残余风险写进文档而不是宣称已修。

---


---

## 三、deferred 闭合与归档台账（原 implementation-artifacts/deferred-work-archive.md）

> 迁移注记：活动项不在本节（真源=open-items.md「活动（未闭合）条目」节）；已闭合编号索引在本文 §四；「正文见 archive 的 X 小节」系旧档案用语，正文以 git 历史为准。

### 已按 Epic 归档

| ID | 主题 | 状态 | 正文 |
| --- | --- | --- | --- |
| Z-D10 / Z-D11 / Z-D18 / Z-D20 | Epic 48 TCP 入口与日志审查 | 已闭合 / OBSOLETE | [`epic-48.../deferred-work.md`](../epics/epic-48-TCP网络接口周期/deferred-work.md) |
| Z-D13 / Z-D14 / Z-D15 / Z-D19 / Z-D21 / Z-D22 / Z-D23 / A8 / A9 / A10 / A12 / A15 / A16 / A17 / A18 / A19 / A23 | Epic 50 网页控制台审查 | 已闭合或裁定维持现状 | [`epic-50.../deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md) |
| Z-D24 / A2 | Epic S1-S4 沙箱裁定 | 已闭合（裁定不实施） | [`epic-S1-S4.../deferred-work.md`](../epics/epic-S1-S4-沙箱硬化周期/deferred-work.md) |
| A25 / A26 / A27 / A28 / A33 / A37 / A38 / A39 | Epic 51 Goal/workflow 收口优化 | 已闭合 | [`epic-51.../deferred-work.md`](../epics/epic-51-goal-workflow优化周期/deferred-work.md) |

### 本轮闭合（2026-10-26 S-6 归一 + 2026-11-02 小步清债 + 2026-11-05 审计语义收窄；证据齐备，**不是**退役）

> 这些条目原先散在 `deferred-work.md` 的「仍需维护的观察」与 Epic 52 review 段里。S-6 归一时逐条核对代码，
> 确认已被既有实现或本轮 E1 闭合。与「退役」的区别：这里有可复跑的判据，不是「不做」。

| ID | 主题 | 闭合证据 |
| --- | --- | --- |
| A45 | `KeyboardInterrupt` / `SystemExit` 与 `CancelledError` 的中断语义不完全一致 | 语义已于 2026-10-23 裁定（A39）；本轮 S-3 把「三分支 → `cancelled`、其余 → `executor_failed`」固化成 `docs/frame.md` 的矩阵表，由 `tests/test_workflow_transition_reason.py::test_interrupt_matrix_matches_absorb_semantics` 与 `::test_interrupt_matrix_covers_vocabulary` 双向钉住 |
| A46 | 异常处理中的 `transition()` 理论上可能覆盖原始异常 | `src/heagent/engine/workflow_transition.py:41` 的 `raise … from exc` 保留 cause 链；`tests/test_workflow_transition_reason.py::test_transition_failure_preserves_cause_chain` 断言 `__cause__` 为 `KeyError`；`scripts/mutation/mutate_state_invariants.py` 的 M5（去掉 `from exc`）会把它打红 |
| A47 | `reason: str(exc)` 可无上限写入 `next_action` / `blocked_reason` | `src/heagent/engine/workflow_runner.py:41` `_MAX_REASON_CHARS = 2000` + `:53-57` `_bounded_reason`（A37 已落）；`tests/test_workflow_transition_reason.py::test_bounded_reason_caps_without_raising` 与 `::test_oversized_reason_is_truncated_on_write` 钉住 |
| A48 | `workflow_step_failed` 未记录驱动转换的事件类型；checkpoint 缺 `last_event` / `transition_reason` | `last_event` 已由 A38 落地（`workflow_runner.py:149`、`checkpoint.py`）；`transition_reason` 由本轮 S-1 补齐（字段 + 唯一写点 + 双向往返）；`workflow_step_failed` 的 `transition_event` 在 `:408` / `:700` 两处发射 |
| A50 | `auto_archive._append_archive` 无锁 read-modify-write（origin=新增，2026-10-29 epic-59 审查落账；2026-11-02 闭合） | `src/heagent/memory/auto_archive.py` 的 `_append_archive` 改走 `atomic_update_text`（归档文件自身 `.lock` 内读改写，与 `memory/compact.py::_append_archive_section` 同款）。判据 `tests/memory/test_auto_archive.py::TestArchiveAppendSerialization`（2 例：① 机制——归档路径必须出现在 `atomic_update_text` 调用里；② 行为——两写者并发追加两段小节都在）。判据强度已用组件副本变异验证（2/2 变红）：把 `_append_archive` 退回裸读写即打红。`docs/frame.md` §4.6 补「归档文件自身的追加也在自身 `.lock` 内读改写」一句，判据条数 14 → 16 例 |
| A49 | `EmbeddedHttpService.failure` 传播路径缺直接测试（2026-11-02 闭合） | 真实双 listener 故障注入已落地：`tests/test_cli_http_lifecycle.py::test_one_listener_dying_is_surfaced_while_the_others_keep_serving`——真 HTTP server + 两个真 WS listener（真 socket / 真端口），在 **uvicorn 自己的 poll 循环**里注入（`Config.callback_notify` 抛错 ⇒ `Server.main_loop` 在 tick 中抛出，不替换 HeAgent 的 `serve_forever`），断言 `failure` 拿到该异常且不被后续抖动覆盖、兄弟 listener 仍应答（裸 HTTP 状态行）、HTTP 健康端点仍 200、`close()` 后历史失败不被清空。判据强度已用组件副本变异验证（去掉 `_failure = error` 即打红）。`docs/frame.md` §4.17「默认 CLI 自启动」行补该传播链与判据落点 |
| A44 | 交互 REPL 不挂事件 rollout sink（2026-11-02 闭合） | `src/heagent/cli/interactive.py::_run_chat` 在引擎构造后与单次模式同口径订阅 `_build_event_sink(settings, json_output=False)`（默认关闭不变，rollout 含工具原始输出；REPL 无 `--json` ⇒ sink 恒不含 stdout 流）。判据 `tests/test_cli_events_rollout.py`（2 例成对：① 开关关闭 ⇒ 一轮跑完后零 rollout 文件，且先断言 provider 真被调 1 次；② 开关打开 ⇒ `<rollout_dir>/<run_id>/rollout.jsonl` 落盘，kinds 含 `run_started` 且以 `run_completed` 收尾）。判据强度已用组件副本变异验证（去掉订阅 ⇒ 「开关打开」用例变红，「关闭」用例保持绿）。`docs/frame.md` §4.12 补「订阅点」一段 |
| A40 | 审计基线已脏文件检测盲区（2026-11-05 闭合） | Δ 由「after 路径集 \\ before 路径集」改为**内容指纹**比较：会话前采集 `_WriteAuditBaseline`（Git 证据 + 已脏 tracked 路径的流式 sha256），会话后用自己的指纹表逐路径比对（`_content_fingerprints` / `_fingerprint_paths`，仓库根相对解析同 A43）。既有脏文件被本 Story 再改 ⇒ 指纹变化 ⇒ 判负；未改动的既有脏文件不误报。判据 `tests/test_story_write_audit.py::test_dirty_baseline_file_touched_again_is_flagged` / `::test_dirty_baseline_file_untouched_is_not_flagged`；判据强度 `scripts/mutation/mutate_write_audit_content_delta.py` M1（退回路径差集即红）。残余：文件读不到（权限 / 中途消失）记空串 ⇒ 与「基线不存在」同向（多判负、不漏判）；把既有脏改动**还原成 HEAD 内容**会让该路径离开变更集、无法捕获（净效果为零，方向仍是多判负）。`docs/frame.md` §4.13 审计段同步 |
| A42 | 违规写无补救语义（2026-11-05 闭合） | 条目原文要求「人工清理指引**或**回滚工具」，本轮交付指引面：判负时把越集路径 + 基线 revision 写进 `workflow_write_audit` 事件留档（闩后串行重跑的新基线已含旧违规 ⇒ 该事件是唯一持久记录），reason 内给 `git diff <base> -- <path>` / `git restore --source=<base> -- <path>`（新建路径改为删除）。判据 `::test_violation_event_records_paths_base_and_remediation` + 变异 M2 / M3。残余 = 自动回滚未做（需会话前快照，属 AD-20 层，非本条目要求） |
| A43 | `_host_artifact_relpath` 参照系（2026-11-05 闭合） | 旧记载的两条前提经实测**否证**：`Path.relative_to` 在 Windows flavour 大小写不敏感、唯一调用点 `_goal_verify_workspace` 已 `.resolve()`。真实残量 = 三源参照系不同（`git diff --name-only` = 仓库根相对、`git ls-files --others` = cwd 相对、产物 = 工作区相对）；收窄 = `_git_toplevel` + `_repo_relpath` 把产物换算成仓库根相对后并入 tracked 豁免，untracked 侧维持 cwd 相对（同根部署为恒等变换）。判据 `::test_repo_relpath_reference_system_branches` / `::test_subdir_workspace_excludes_host_artifact` / `::test_subdir_workspace_untracked_artifact_not_warned` + `scripts/mutation/mutate_write_audit_reference.py` 4/4 红。**2026-11-05 用户裁定：残余可读作已足够**（`GIT_DIR` 重定向 / 走不到 `.git` 时退回旧语义，方向是多判负、不漏判）⇒ 本轮闭合，不另立收窄周期 |
| A51 | 发布缺口：无 CHANGELOG 载体、无「版本号 ↔ git tag」守卫（origin=新增，2026-11-11 S-14 落账） | `CHANGELOG.md` 建立（Keep a Changelog 形态：`## [Unreleased]` 常驻 + `## [0.9.0] - 2026-11-11` 首节，并写明 0.9.0 之前的历史未逐条回填及追溯命令）。版本真源守卫 = `tests/test_release_workflow_contract.py` 共 6 例：两处真源相等（ast 取 `__version__` + tomllib 取 `project.version`）/ 版本纯 `X.Y.Z` / HEAD 带 `v*` tag 时 tag == 版本 / CHANGELOG 有 `Unreleased` 段 / CHANGELOG 有当前版本节且带日期 / CHANGELOG 标题格式合法且 `Unreleased` 不带日期。变异 **6/6 红**（改 pyproject 单侧 / 写成 `0.9` / 副本打 `v1.0.0` / 删 `Unreleased` / 版本节改名 / `Unreleased` 带日期）。`pyproject.toml` 的 `[project.urls]` 增 `Changelog` 指向 CHANGELOG.md。2026-11-11 闭合 |

- **52-3 AC1（端到端围栏贯通冒烟）**：已闭合（2026-10-26，Epic 57-3）——真实注册表 `file_write` handler 经
  `policy.evaluate_tool_call → executor.execute` 全链贯通：集内写真实落盘、越集写围栏 BLOCKED 且 handler 零触达。
  贯通首跑暴露一处真实缝隙：真实 handler 从运行时绑定（`bind_workspace_root`）解析根而非 RunContext，测试已按主链路
  `_runtime_scope` 同形态绑定。证据 `tests/test_write_allowlist.py::test_e2e_chain_*`（2 例）。
  **附带发现（不另行立项）**：围栏（policy 用 RunContext 根）与工具（handler 用运行时绑定根）在二者不一致时可出现
  「围栏判 A 根、工具写 B 根」的错位窗口——当前主链路两者恒同源（loop 每 run 绑定 `run_context.workspace_root`），
  错位不可达；登记供未来改 run 上下文装配时复核。

### 本轮非目标（heagent-improvement-plan，2026-11-11）

> 来源：`_he-output/works/heagent-improvement-plan/step-04-define-product-scope/report.md` 的「非目标」段（11 条）。
> 这些是**本轮明确不做**的项，不进活动表（不是 A 号待办），故不参与活动计数；`NG-` 前缀与 A 号体系隔离。

| ID | 非目标 | 触发条件（何时重新评估） | 严重度 |
| --- | --- | --- | --- |
| NG-1 | 不从零建 CI、不新增 CI job（`ci.yml` 已有 8 job） | 勘差表（S-6）举证某 FR 缺口无法由现有 job 关闭 | Low |
| NG-2 | 不启用 merge 自动发 PyPI beta（Q2） | 发布频率 ≥ 每月 1 次，且已配置 Trusted Publisher | Medium |
| NG-3 | 不做 auto-bump（FR12.3） | 手工改版本号导致 ≥2 次发布事故 | Medium |
| NG-4 | 不做 CHANGELOG 自动生成（FR12.4） | 用户/下游要求按版本查看变更，或发版频率 ≥ 每月 1 次 | Low |
| NG-5 | 不做 devcontainer（FR13.1 残余） | 新贡献者环境搭建受阻 ≥2 次，或 CI 矩阵不足以复现问题 | Low |
| NG-6 | 不在拆分期下调覆盖率门（Q3） | 不得触发；下调即违反 INV-6 | High |
| NG-7 | 不一轮拆多个文件（RQ-4） | 不得触发；违反则三证据无法归因 | High |
| NG-8 | 不删除既有架构守卫、不缩减 `FORBIDDEN_RUNTIME_IMPORTS`（RQ-5） | 不得触发；违反即 INV-4 失效 | High |
| NG-9 | 不改 `network/` 既有 4xx/5xx 键名/语义/状态码，不把错误码做成对外 ABI（Q5 / RQ-8） | 有外部使用者明确要求，且愿意接受 breaking 版本 | High |
| NG-10 | 不在传输层载荷携带文档链接（Q6 / RQ-9） | 有外部客户端明确要求从错误体取文档链接 | Low |
| NG-11 | 不把 `pip-audit` 转硬门（OQ-3） | 出现高危 CVE 且现有软门未及时暴露 | Medium |
| NG-12 | 不为文档引入新运行时依赖（`network/` 受 stdlib + pydantic + pub.safe_logging 约束） | 不得触发；违反即破 INV-4 | High |

### 显式退役（`retired`）

> 语义：**已裁定不再修**（区别于「已修复归档」）。混进归档段会让后人二次调查同一问题。
> 每条必须齐备 5 字段：`retired_reason`（退役理由）／`replaced_by`（替代守卫，`file:line` 或 story id）／
> `decision_ref`（裁定出处：日期 + 记录位置）／`retired_on`（退役日期，须实测系统日期）／
> `recheck_condition`（复活条件）。

| ID | retired_reason | replaced_by | decision_ref | retired_on | recheck_condition |
| --- | --- | --- | --- | --- | --- |
| （当前 0 条） | — | — | — | — | — |

**为什么本轮 0 条**：退役需要「已裁定不修」的前提，而本轮已批决策只覆盖「继续挂起 / 继续挂账」（OQ-3 / OQ-4 / OQ-5），
没有任何一条被裁定为「永不修」。缺裁定指针却填满 5 字段等于伪造决策，故留空表 + 结构就位。

### 跨周期勘察与裁定索引

以下条目没有唯一 Epic 归属，保留在总账中作为历史索引；详细当前边界以 `docs/frame.md`、`docs/goal-workflow.md` 和源码为准。

| ID | 主题 | 结论 |
| --- | --- | --- |
| Z-D1 / Z-D2 / Z-D4 / Z-D5 / Z-D6 / Z-D7 / Z-D8 / Z-D9 / Z-D12 / Z-D16 / Z-D17 | 架构、解析、日志、沙箱和会话存储勘察 | 已闭合或裁定维持现状 |
| Z-D3 | provider 回退骨架是否统一 | 评估结论为不收敛：chain、key_rotation、switchable、router 的回退条件、粘性和索引语义有意不同；补充互指注释，行为不变（证据：`providers/{chain,key_rotation,switchable,router,retry}.py`、`tests/test_retry.py::TestPoolFallbackPolicy`、提交 `beea1a2`） |
| A3 / A4 / A5 / A11 / A24 | 入口、GUI、观测与运行姿态 | 已闭合，正文留在相关周期记录或提交证据中 |
| A1 / A6 | 技能资源与路径级审批前置裁定 | 裁定维持现状或维持条件性；边界见 `docs/frame.md` 五 |
| A29 / A30 / A31 / A32 | 2026-10-07 架构简化与层次收敛 | 已闭合；证据见提交记录、源码和测试 |
| 技能资源 TOCTOU 残余竞态专项评估 | 已评估（2026-10-20）。事实：单一安全内核 `path_safety.read_bytes_under_root`（围栏 resolve → 加固 open → fstat 普通文件校验 → 持 fd 读满）双通道——POSIX 逐组件 openat（2026-09-27 硬化）收窄至组件级竞态，Windows 无 dir_fd 走整路径回退（窗口与硬化前同宽，本机实际通道）；importer 落地为 verify-before-land（temp 复制后复核逐文件摘要，通过才 `os.replace`，检查期哈希→落地拷贝的窗口已闭合）；包读侧另有钉定摘要校验。裁决：check 与 use 同进程同权限，TOCTOU 不跨越信任域——能赢下任一窗口的攻击者无需竞态即可直写技能根或经 shell 直读凭证（frame.md 既有登记面），无新增可提升暴露面 ⇒ **不另立收窄周期**，维持 OS 沙箱兜底立场。附带确证：manifest.csv / `_hash` 直读为 load-bearing 例外（csv raw newline 语义 / 任意位置临时树哈希，围栏不适用）；`skill_meta.load_meta` 在 src 内零调用方（死代码路径，非活窗口）；`SkillStore._read_text` 实例锁已覆盖 Windows 读写互斥 | 边界=`tools/path_safety.py`、`skills/{skill_store,skill_packages,skill_importer}.py` |
| 架构简化再勘验（2026-11-06） | 已裁定（2026-11-06，方案 news/simplify_plan.md）。2026-11-03 遗留 4 候选逐一按符号重测：A1 `_execute` 终态五分支净≈0（共享尾缀仅 append+close 2 行×5）；A2 串行/批失败合并净−4~6 但两路闩置位刻意不对称（动 AD-18 闩序，中险不对价）；A3 `_serve_web`⊕EmbeddedHttpService 净−10~15 但公告文案两路刻意不同+9 处 setattr patch 缝（维持高风险裁定）；A4 `skill_meta.load_meta` 复核仍 test-only（默认保留）。**全部裁定不做，代码精简批准=0**；简化杠杆转架构级：B1 统一执行世界 seam（shell.py session 静默忽略 command_runner + session.py:191 内部又读 slot，双面并存仅运行期 WARNING）待 BMAD 立项；B2 文档纪律三件已落 frame.md §4.15/§8.4/§4.6；B4 SKILL.md 双开关已落 `83b2f22`（2026-11-06）。勿对 catalog.py 再提无净行数预估的去重 | `memory/dream.py`、`network/http_server.py`、`engine/workflow_runner.py`、`cli/http.py`、`skills/skill_meta.py`；边界=frame.md §4.6/§4.15/§8.4 |
| 架构简化从零再勘 v2（2026-11-06） | 已执行（方案 news/simplify_plan_v2.md，git 忽略）。批次 5/6/7 已提交（`7edd546`/`a703d7c`/`75118f7`，生产码净负、测试面 +42 系钉策略代价）；批次 8（C6 流事件映射统一）执行期裁定不做（四轴契约面刻意不同）；批次 3=B4 双开关已落 `83b2f22`；批次 9 卡 A housekeeping 迁回顶层已落 `3dec905`（spec 在 `epics/epic-60-结构精简周期/`）；卡 B provider 装配规则迁 providers/composition.py 已落 `89ff596`（同目录 spec，呈现薄壳保缝、+2 契约钉测试）；**卡 C+D（goal 文档持久化迁 document.py / 写审计 12 符号迁 write_audit.py，emit 注入 + 变异脚本随迁）与卡 E（runner 构造期参数化 + 双 runner 构造期判定 + 三钉）已实施**（同日完成，spec 均在 `epics/epic-60-结构精简周期/`；批次 9 全收口） | 边界=frame.md §4.6/§4.15/§8.4 |
| fact_compact 崩溃窗口定向审查 | 已审查（2026-11-06，dsh 对标 #3），**无缺口、无代码改动**。窗口=「留底已写（archive 小节带 `fact_compact` 标记）→ MEMORY.md 比较后写前」崩溃：残留为留底与现行**并存的可检测重复态**——留底小节即崩溃遗留的合成痕迹；无静默丢失路径（归档并发覆盖已由 A50 闭合；比较后写防并发吞写，冲突放弃本批、留底保留）；同批 merge 可原样重放恢复（source 精确匹配仍唯一在场），失败方向与「宁重复不丢失」一致，不引入锁文件语义。崩溃窗口口径已落 frame.md §4.6 语义压缩段 | `memory/compact.py`（compact_facts/_append_archive_section）；边界=frame.md §4.6 |



---

## 四、已闭合 A 编号索引与修正记录（迁自 consolidated-overview.md §17.4-A/B/E）

> 迁移注记：原「台账 A 编号登记表」引用系旧布局用语，登记段在 epic-50 周期 deferred-work.md；Z-D8/Z-D9 闭合档案在本文 §三。

> **2026-11-15 起**：完整正文（触发条件 / 状态 / 裁定指针）一律以 `open-items.md`「活动（未闭合）条目」节为准；闭合与归档历史见本文 §三。本表只做导航、**不再复制**（以下为历史沿革，保留原样：2026-10-26 S-6 四态归一新增 A40–A44 / A49；2026-10-29 epic-59 审查落账 A50，其中 A45–A50 均已当轮或后续批次闭合，见 archive「本轮闭合」表；2026-10-20 落账 **A34**–**A36**（会话并发写残余 / HTTP 持久化 / 全局签名入口，0e8a330）挂起待裁定或待触发；2026-10-23 登记并**当日实施闭合**的 **A37**–**A39**（reason 长度上限 / 事件与 checkpoint 的转换原因 / KI·SystemExit 取消语义）已按 Epic 51 归档，正文见 `epics/epic-51-goal-workflow优化周期/deferred-work.md`——它们**不进**下方历史索引表（该表口径仍是 A1~A19 + A23~A33 的 26 行已闭合编号）；历史沿革：2026-10-07 两轮 /simplify 清理补录 A25~A33 ⇒ 由 0 复增至 9，同日第五轮批量处置 A29/A30/A31/A32 ⇒ 9→5，同日第六轮按用户指令闭合 A25 / A26 / A27 / A28 / A33 ⇒ 第二次清空；2026-09-28 曾**首次清空**——A8 / A10 / A12 / A15 / A16 按裁定、A1④ 交付、A1 与 A6 归档）。下表保留 **26 行已闭合 / 已失效**的编号（A1~A19 + A23~A33 全部划线），供旧引用追溯。**编号口径（2026-09-28 统一）**：本表 A 号与台账的「**A 编号登记表**」**已对齐**——A1~A19 + A23/A24 一一对应 21 个事项（A20~A22 为撤号，不复用；A25~A33 为 2026-10-07 新登记批次），**同号异义已消除**（旧账：A19 曾同时指「掩码域后缀制」与「原生目录选择端点默认开」，A17/A21 同指 R5 收敛判据）。撤号不复用，旧号对照见登记表的「旧号对照（撤号 / 让号）」段；引用**一律以台账登记表为准**。

| # | 条目 | 严重度 |
|---|------|--------|
| A1 | ~~Epic 46 技能资源 TOCTOU 后续（descriptor-relative open / 目录句柄、可信导入 snapshot、OS sandbox）~~ —— **已闭合**（2026-09-28 **裁定维持现状**：逐组件 `openat`（2026-09-27）与导入形态的内容钉 + 读时校验（2026-09-28）均已交付，残余为平台/形态固有；「可信导入 snapshot」作为正文内的未闭合面保留；正文见 `deferred-work-archive.md` 的「A1」小节） | — |
| A2 | ~~MCP stdio server 子进程未接入沙箱（其 env 亦不经 `scrub_sensitive_env`）~~ —— **裁定 (c) 不实施**（2026-09-27；env 面经 SDK 实测**排除**——只继承 `DEFAULT_INHERITED_ENV_VARS`，真缺口只剩 spawn 面）→ 归档为 **Z-D24**（正文见 `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md`） | — |
| A3 | ~~`cli.py` / `cli_goal.py` 职责再拆~~ —— **已闭合**（2026-09-26，`49168b4` + `42d7331`；正文见 `deferred-work-archive.md` 的 A3 小节） | — |
| A4 | ~~GUI 原生事件渲染（改消费事件契约 v2，替掉 stderr 转发）~~ —— **已闭合**（2026-09-28，A4a 事件驱动渲染 + A4b 消息 sink 替掉 stderr 转发；A4c 有意不做，正文见 `deferred-work-archive.md` 的「A4」小节） | — |
| A5 | ~~观测粒度残余（façade 路径 `run_failed` 恒 `duration_ms=0`；story batch 为整批一条事件）~~ —— **已闭合**（2026-09-23 `1f99cc0`，2026-09-27 台账复核；正文见 `deferred-work-archive.md` 的 A5 小节） | — |
| A6 | ~~路径级审批分级（条件性，前置未发生）~~ —— **已闭合**（2026-09-28 **裁定维持条件性**：审批是工具级、越界路径在围栏处即硬阻断，无分级对象；触发条件与判据草案移入 `docs/frame.md` 五，正文见本文 §三「跨周期勘察与裁定索引」A1 / A6 行） | — |
| A7 | ~~TCP 入口不写 rollout（`EVENTS_ROLLOUT_ENABLED` 对 `tcp-server` 是死开关）~~ —— **OBSOLETE**（2026-09-27，入口随 Epic 48 整体删除 → 归档为 Z-D18） | — |
| A8 | ~~跨项目并发无全局上限（D9 采纳后的已知缺口，计划期登记）~~ —— **已闭合**（2026-09-28 **裁定维持现状**：并发随项目数线性是 D9 的有意语义；服务级总额已作可选 `HTTP_MAX_TOTAL_INFLIGHT` 交付，默认 0 = 不限；正文见 `deferred-work-archive.md` 的「A8」小节） | — |
| A9 | ~~运行时归因与兜底族（`deadline_reason` 永久保留 / `tools_in_flight` 不衰减 / SSE「先查后加」）~~ —— **已闭合**（2026-09-27，`a1f7c67`；正文见 `epics/epic-50-网页控制台周期/deferred-work.md`） | — |
| A10 | ~~控制台端点在唯一事件循环里做同步 I/O（会话列表 / 配置面板 / 注册表）~~ —— **已闭合**（2026-09-28 **裁定维持现状**：其余落点均已离线到 `to_thread`，仅剩 `_runtime_for` 的 1 读 + 1 stat 有意保留并写明升级条件；正文见 `deferred-work-archive.md` 的「A10」小节） | — |
| A11 | ~~非回环运行姿态 + cron 跨会话后置执行~~ —— **已闭合**（2026-09-27；2026-09-28 状态归一，两半均已了结）：② cron 跨会话后置执行已闭合（`5a8a21e`，`enable_cron=False` 时不构造 `JobStore`；**该形态已于 2026-10-28 按用户裁决撤销** —— 网页入口改为 `enable_cron=True`、与交互模式/GUI 共用同一份 `jobs.json`，handler 仍不启停调度器，风险显式接受，见 `docs/frame.md` 4.17/4.18），① 非回环姿态已裁定维持现状（2026-09-28 编号统一时，原独立登记的旧 A20「总结」并入本条）；正文见 `deferred-work-archive.md` 的 A11 小节 | — |
| A12 | ~~浏览器级 UI 验收不在 CI、也不含真实 LLM 运行~~ —— **已闭合**（2026-09-28 **裁定维持现状**：**保持手动**——冻结边界禁 playwright，真浏览器这一步不可省略；正文见 `deferred-work-archive.md` 的「A12」小节） | — |
| A13 | ~~「高影响键的差异化确认」缺后端风险标记~~ —— **已闭合**（2026-09-27；事实源 = `RESOURCE_CEILINGS`，正文见 `epics/epic-50-网页控制台周期/deferred-work.md`） | — |
| A14 | ~~写入通道与保真写的四类低危残余（`.env.lock` 落点 / 回滚失败文案 / 写锁内 I/O / 末行无换行）~~ —— **已闭合**（2026-09-27，四面全处置；正文同 A13 目录） | — |
| A15 | ~~网页请求可拉起宿主 GUI 进程（Story 50-8 R2 有意引入的新暴露面；含三种不可用环境）~~ —— **已闭合**（2026-09-28 **裁定维持现状**：A19 之后默认关闭 ⇒ 显式 opt-in 才出现，不做更强授权；正文见 `deferred-work-archive.md` 的「A15」小节） | — |
| A16 | ~~真实原生窗口无法自动化验收 + 网页侧读取结果收敛依赖 `Error:` 前缀判据（Story 50-8 R2/R5）~~ —— **已闭合**（2026-09-28 **裁定维持现状**：人工验收为唯一路径，迁移条件已写进判据本体；正文见 `deferred-work-archive.md` 的「A16」小节） | — |
| A17 | ~~R5 收敛判据对「正文以 `Error:` 开头的文件」失效（AC9 两句话互斥）~~ —— **已闭合**（2026-09-27 裁定收紧规格；正文见 `deferred-work-archive.md` 的「A17」小节） | — |
| A18 | ~~「共 N 个会话」在 N > 200 时静默少报（服务端硬上限截断、协议无 `total`）~~ —— **已闭合**（2026-09-27，`7b9015f`；正文同 A9） | — |
| A19 | ~~原生目录选择端点默认开~~ —— **已闭合**（2026-09-27 裁定默认改按需：`--dialog-backend` 默认 `none`；正文见 `deferred-work-archive.md` 的「A19」小节） | — |
| A23 | ~~掩码域后缀制（`*_BASE_URL` 里的凭证原样回显）~~ —— **已闭合**（2026-09-27 裁定维持现状；2026-09-28 由旧 A19 改号，正文见 `deferred-work-archive.md` 的「A23」小节） | — |
| A24 | ~~GUI 事件日志在环形缓冲满后永久停止渲染（+ 暂停即丢事件）~~ —— **已闭合**（2026-09-28 当日发现当日修；改动面 `pub/event_lines.py` + `gui/{observers,widgets/event_log}.py`，正文见 `deferred-work-archive.md` 的「A24」小节） | — |
| A25 | ~~checkpoint id 的 `-parallel-` 残留分支（批次机制遗物）~~ —— **已闭合**（2026-10-07：分支删除；兼容策略 = 容忍读——恢复路径从不按重建 id 找快照，旧格式文件可解析、新写入落新格式 id 不撞 conflict；兼容钉 `test_legacy_parallel_checkpoint_id_recovers_and_rewrites_new_format`；正文见 `deferred-work-archive.md` 下方「A25」小节） | — |
| A26 | ~~`active_stories` 是 `active_story` 的可派生镜像（六写点同步税）~~ —— **已闭合**（2026-10-07：三模型字段派生化删除（旧盘键容忍读），消费方（status_view 投影 / from_checkpoint 恢复）全部接上现场派生；恢复矩阵加第四形态钉陈旧镜像被忽略；正文见 `deferred-work-archive.md` 下方「A26」小节） | — |
| A27 | ~~门事件 emit 隔离包装双份（`cli/goal.py` 与 `engine/workflow_runner.py` 各一份）~~ —— **已闭合**（2026-10-07：`_emit_step_event` 转鸭子契约 + payload 构造入隔离，CLI 门事件改为 `**extra` 委托——隔离契约全仓单份实现；敌意鸭子判据钉住；正文见 `deferred-work-archive.md` 下方「A27」小节） | — |
| A28 | ~~goal-verify 台账审计生命周期 CLI 手写（第三份 claim/execute/finalize 拷贝，且无租约续租）~~ —— **已闭合**（2026-10-07：`LedgerAudit` audit-only 规格 + `renew_lease_while_active` 原语下沉 `engine/ledger.py`，`ToolExecutor.execute` 增可选 `audit=`；CLI 三助手删除、在途续租接管修复审计面失配；变异体 6/6 变红；正文见 `deferred-work-archive.md` 下方「A28」小节） | — |
| A29 | ~~会话/运行热路径的四处重优化（checkpoint O(N²) / 会话列表全量解析 / 无 title 整历史校验 / token 估算逐字符）~~ —— **已闭合**（2026-10-07 当日四面全修：写只读 / C 级计数 / mtime 排序零解析 / 元数据备忘录；探针 ② 131x / ③ 7x；正文见 `deferred-work-archive.md` 下方「A29」小节） | — |
| A30 | ~~goal 域两处重复收敛~~ —— ① **评估结论 = 不收敛**（2026-10-07：锁差异是在码裁定——审查 #15 + goal_mutex(A32②) + 双维 sentinel 结构性需求；护栏 `test_store_concurrency_stance_divergence_is_intentional` 钉住）；② **已闭合**（`frontmatter_name_list` 单源核，宽容度分叉保留并带判据；正文见 `deferred-work-archive.md` 下方「A30」小节） | — |
| A31 | ~~引擎层的方法论与解析错位~~ —— **已闭合**（2026-10-07：① `engine/artifacts.py` 整模块删除（零运行期调用方）② `StorySpec`→`pub/types.py` + 解析 177 行→`goal/workflow_loader.py` ③ BMad 兜底文案迁角色 md 声明（`delegation_fallback` frontmatter 键），工具层零文案副本；正文见 `deferred-work-archive.md` 下方「A31」小节） | — |
| A32 | ~~治理与互斥的层级归属~~ —— **已闭合**（2026-10-07 三面全修：①② 见 2026-10-07 第三轮 + ③ `goal/` 11 个私有符号转公共名，入口层不再引用例层私有符号；正文见 `deferred-work-archive.md` 下方「A32」小节） | — |
| A33 | ~~可派生镜像与边际重复（artifact_refs 镜像 / dispatch 前导 11 处）~~ —— **已闭合**（2026-10-07：① `artifact_refs` 随 A26 同批派生化删除（不可达兜底一并删）② `_goal_bound_workflow()` 收敛 11 处前导，`_goal_mutex` 持有面逐字保持；正文见 `deferred-work-archive.md` 下方「A33」小节） | — |

> **旧编号对照（2026-09-18 版）**：旧 A1~A4 = 本文 A1 / A2 / A3 / **A6**；旧 A5（`RoleSpec.sandbox_profile` 死字段）与旧 A6（沙箱进程数限额）已于 2026-09-18 闭合，故新编号里不再出现。改编号只为与台账条目顺序一一对应——正文一律以台账为准。
> **2026-09-28 编号统一**：本表与台账「A 编号登记表」对齐（A1~A19 + A23/A24 一一对应 21 个事项）；旧 A21 → **A17**（R5 收敛判据失效）、旧 A22 → **A19**（原生目录选择端点默认开）、旧 A19（掩码域后缀制）→ **A23**、旧 A20（非回环运行姿态「总结」，A11 的重复登记）→ **A11**。`src/` / `tests/` 注释引用的 A9 / A11 / A13 / A14 / A18 **号未变**。
>
> 上述两项的闭合档案（「A5 取删除而非激活」「A6 两后端语义不对称」的完整理由与证据）见 `deferred-work-archive.md` 勘察类 **Z-D8 / Z-D9**，此处不再复述。
#### B. 文档此前列为待办、实际已闭环（10 条，2026-09-24 修正）

| # | 原表述 / 出处 | 实际状态 | 证据 |
|---|---------------|----------|------|
| B1 | bmad-build Step 07 未声明 `max_iterations`（12.6、17.3、retro 1.14） | **已闭合** | `.heagent/skills/he-goal/workflow.md:208` 声明 `max_iterations: 100`；`d7dc758`（E41-D6） |
| B2 | GUI `/goal` 输出未进 RichLog、无取消控制（12.3） | **已收口** | stderr→RichLog + Esc 取消 + GUI 持有 `CronScheduler` + pilot 交互测试；`44ab001`（E41-D7） |
| B3 | goal 指针 / `GOAL.md` 仅进程内 asyncio 锁（16.2 #10、17.3） | **已修复** | `persist.file_lock`（`persist.py:394`）+ `_goal_mutex`，7 个变更入口全接；`855d135`、`tests/test_goal_cross_process_lock.py`（E41-D5） |
| B4 | 凭证 deny 缺用户入口（12.1） | **已交付** | `.heagent/path_deny.json`（`tools/path_safety.py:206-257`）；`63806d3`（F-D1） |
| B5 | 沙箱资源限额 / 高级参数 / per-tool 粒度（13.1） | **已交付**（默认关闭） | `SANDBOX_MEMORY_LIMIT_MB` / `SANDBOX_CPU_SECONDS` / `SANDBOX_PROFILES` / `SANDBOX_TOOL_PROFILES`；`0582a03`（S-D4..D6） |
| B6 | E47-D1「ledger 记录在途被删」（12.6、17.3） | 续租 + 回写容错**已修**；**仅「施动者未唯一归因」仍开** | `cc8cb3f`；契约写入 `agent/tool_execution.py` docstring |
| B7 | `spec-business-data-integration.md` 为未启动母规划 spec（13.2、附录） | **文件 2026-09-15 已删除**（仅存 git 历史） | `_bmad-output/README.md:165,167`；`62f09a5` |
| B8 | `agent/loop.py` C901 超标「长期应拆分」（16.2 #5） | **已裁定接受** | 抽出 `_inject_*`/`_append_*`/`_finish_run` 后实测仍 17 > 15，依据已写入 `agent/loop.py:404,418` docstring |
| B9 | 全库指标 1896 passed / 112 天 / ~51,200 行（17.1、retro 四） | **已刷新** | 2026-09-18 实测 1983 passed / 9 skipped、覆盖率 90.85%、`src/` 24,161 + `tests/` 28,337 行、115 天（2026-09-22 再刷新为 2061 passed / 90.88%，见 §17.1） |
| B10 | `_bmad-output/README.md:13` 仍描述 `implementation-artifacts/` 含 `deferred-work.md` 与母规划 spec（原属 C 组） | **已修正** | 2026-09-24 实测：`:13` 已写 `deferred-work-archive.md`、`:170`/`:172` 把母规划 spec 标注为「2026-09-15 已删除」——该条移出 C 组 |

#### E. 已决策关闭（不再排期）

- 全局/home 级 MCP 注入签名入口（won't do，2026-09-15；项目级 `.heagent/injection_signatures.json` 已交付）。
- 把 MCP Resources / Prompts 增强纳入必要开发范围（MCP 后续不作必要功能）。
- 业务数据整合母规划 spec（`spec-business-data-integration.md` 文件 2026-09-15 已删除）。
- 编号冲突（两份 Epic 14）——2026-07-23 统一编号空间后无冲突。


---

## 五、历史 code review 摘要与已闭合索引（原 implementation-artifacts/deferred-work.md）

> 迁移注记：活动指针段已删（活动真源=open-items.md）；「archive 的本轮闭合段」指本文 §三。

> 已闭合的 10 条（A40 内容级增量 / A42 判负补救指引 / A43 参照系换算 / A44 交互 REPL 挂 sink / A45 中断语义 / A46 cause 链 / A47 reason 无上限 / A48 失败事件缺驱动字段 / A49 双 listener 故障注入 / A50 归档追加加锁）正文与证据
> 在 archive 的「本轮闭合」段；Epic 52 审计语义 4 项目前只剩 A41（A40/A42/A43 已闭合），不再在本文件重复。

### 已闭合事项索引

| 来源 | 结论 | 证据 |
| --- | --- | --- |
| Story 51-4 | workflow/revision 冻结绑定已接入 `/goal verify`；执行期证据复用完成门，受治理重跑经过审计链 | `tests/test_goal_workflow_selection.py::test_frozen_revision_flows_into_verify_step`；Story 51-6/51-8 |
| Story 51-6 | workflow 与 revision 半键绑定规则已明确并有正反向测试 | `src/heagent/goal/application.py::read_workflow_binding`；`tests/test_goal_workflow_selection.py` |
| Story 51-7 | GoalScript 后续步骤声明、持久化恢复、受控 facade 和限额已完成；同步 CPU 密集脚本的超时限制仍依赖 OS 隔离 worker | `docs/frame.md` §4.13.1；`tests/test_goal_script_*.py`；`src/heagent/goal/script_runtime.py` |
| Story 51-2（异常路径落盘） | **已闭合**：`run_step()` 的异常分支经 `_absorb_step_exception()` 转换后由 `_persist_interrupted()` 落盘（`asyncio.shield` + 双层 except，落盘失败只告警不替换原异常） | `src/heagent/engine/workflow_runner.py::_persist_interrupted`；`tests/test_story_loop.py::test_story_failure_persists_failed_checkpoint` |
| Story 51-2（多 phase pause） | **生产路径不可达**：`_pause_resume_unlocked()` 首行 `if runner.done` 即返回 `UNCHANGED`（"declarative workflow is already complete"），`runner.pause()` 到不了 `COMPLETED` 态 | `src/heagent/goal/application.py::_pause_resume_unlocked` |
| 52-3 AC1（端到端围栏贯通冒烟） | **已闭合**（2026-10-26，Epic 57-3）：真实注册表 `file_write` handler 经 `policy.evaluate_tool_call → executor.execute` 全链贯通 | `tests/test_write_allowlist.py::test_e2e_chain_*`（2 例）；附带发现见 archive 已归档表 |

当前实现状态以源码、测试、`docs/frame.md` 和 `sprint-status.yaml` 为准；本文件不重复复制完整验收报告。


---

## 六、指标总结

| 指标 | 数值 |
|------|------|
| 总 Epic 数 | **61**（Epic 1–57 + S1–S4），分属 **26 个周期**（25 个 BMad 周期 + 1 个架构优化；2026-10-27 实测） |
| 总 Story 数 | **134 个 story 文件（35 个 `stories/` 目录）**（2026-10-27 实测；历史值：102/28=2026-09-26、118/32=2026-10-23）+ quick-dev 直接执行项（Epic 29–35 等无独立 story 文件） |
| 总测试数 | **3765 passed / 50 skipped / 28 deselected**（2026-10-23 实测；deselect = integration + benchmark + 本机 WSL2 恒红 3 条端口断言） |
| 覆盖率 | **92.47%**（gate 87；`scripts/quality_gate.py` 六门：goal smoke / 回归+覆盖率 / ruff check / ruff format / mypy / bandit `-ll`） |
| 代码行数 | ~96,700（`src/` 42,277 + `tests/` 54,426，2026-10-23 计数；168 / 159 个 `.py`） |
| 外部依赖 | 核心 6（openai / anthropic / tiktoken / pydantic / pydantic-settings / mcp；2026-10-26 起配置条目名 gpt→openai、anthropic→claude）+ 可选（tiktoken 真实 tokenizer；textual GUI） |
| 开发周期 | 2026-05-26 → 2026-10-27（**154 天**） |

---

## 七、待完成工作（2026-09-27 复核）

> **权威来源**：活动（未闭合）条目 = `_bmad-output/open-items.md`「活动（未闭合）条目」节（2026-11-15 起）；Epic/Story 状态 = `_bmad-output/sprint-status.yaml`；安全缺口 = `docs/frame.md` 五。修正表（B 组）见本文 §四。

### 7.1 活动台账未闭合（4 条——A34–A36 + A41，**索引**）

> **2026-09-28 复核**：活动区实测 **2 条**（此前写的 23 条为历史值——其间 21 条条目闭合 / 按归属归档并移出活动区，计数长期未同步；同日第五轮校正为 7、第六轮按产品裁定闭合 A8 / A10 / A12 / A15 / A16 五条、第七轮交付 A1④、第八轮按裁定闭合 A1、第九轮按裁定归档 A6 ⇒ **0 条**，活动台账**首次清空**）；**2026-10-07**：Story 51-8 清理轮按纪律补录 4 条（**A25**~**A28**），同日全项目 /simplify 轮再补录 5 条（**A29**~**A33**，14 项跳过发现按主题归并）⇒ 当前 **9 条**；**2026-10-20**：0e8a330 落账 **A34**–**A36**（会话并发写残余 / HTTP 持久化 / 全局签名入口）⇒ 现行 **3 条**；**2026-10-23**：本轮改进落账 **A37**–**A39**（reason 长度上限 / 事件与 checkpoint 的转换原因 / KI·SystemExit 取消语义，判据 `tests/test_workflow_runner.py`）（同日**已实施并闭合**，正文按归属归档 Epic 51 `epics/epic-51-goal-workflow优化周期/deferred-work.md`）⇒ 现行 **3 条**；**2026-10-26**：S-6 四态归一（active / scheduled / frozen / retired），把 Epic 52 review 的 4 项与 Epic 56-1 的 1 项纳入活动表（A40–A44），并闭合 A45–A48，现行 **9 条**。编号口径（本系列编号与台账编号不同义的两处）见 `consolidated-overview.md` §17.4-A。

> （历史口径）正文原以 archive 活动区为准——该区已迁 `open-items.md`（2026-11-15 起住 `_bmad-output` 根）；闭合台账在本文 §三，逐条摘要历史值在本文 §四。
>
> **旧编号对照**：本条 2026-09-18 版列 A1~A4（TOCTOU / MCP stdio / cli 拆分 / 路径级审批）；新编号前三者不变，**路径级审批移到 A6**。原 A5（`RoleSpec.sandbox_profile` 死字段）与 A6（沙箱进程数限额）已于 2026-09-18 闭合——A5 取删除方向，A6 新增 `SANDBOX_NPROC_LIMIT` + 修正 WinJob `JOB_OBJECT_LIMIT_PROCESS_TIME` 常量（原误写 `0x8` 即 ACTIVE_PROCESS 位）；闭合档案见台账 **Z-D8 / Z-D9**。
>
> **2026-09-28 编号统一**：A 号以台账「A 编号登记表」为唯一事实源（A1~A19 + A23/A24 一一对应 21 个事项；A20~A22 为撤号）；旧 A21 → **A17**、旧 A22 → **A19**、旧 A19（掩码域后缀制）→ **A23**、旧 A20（非回环运行姿态「总结」，A11 的重复登记）→ **A11**；`src/` 与 `tests/` 注释引用的 A9 / A11 / A13 / A14 / A18 号未变。

### 7.2 纪律类滞后（非代码，2026-09-18 实测）

- 6 个 36-39 story 的 frontmatter 仍为 `status: backlog`（`36-1`/`36-2`/`36-3`/`37-1`/`38-1`/`39-1`）。
- `45-1` / `45-2` 无 story 文件（该 epic 仅 `45-3`）；`spec-45-3` / `spec-46-1` 已在归档提交中删除或改名。
- **14 个 epic 的 retrospective 仍为 `optional`**（2026-10-27 实测：25-28 / 38-39 / 43-46 / 49 / 51 / 55 / 57，均未补做）；已补做：36/37/40/41/42（09-18）、Epic 48（09-23）、Epic 50（09-27）。
- `S4-1`（executor emit `sandbox_backend` + `sandbox_pid`）仍 `skipped` —— 沙箱执行轨迹不可追溯。
- `_bmad-output/README.md:13` 仍描述 `implementation-artifacts/` 含 `deferred-work.md` 与母规划 spec——两者均已不存在（现为 `deferred-work-archive.md`；**2026-09-20 已修正该描述**）。

### 7.3 路线图与技术债候选（逐条已核实仍开）

- 🔜 **生产化**：PyPI 发布、Docker Hub 镜像、CI release workflow（`.github/workflows` 目前只有 `ci.yml` + `codeql.yml`）。
- ⏳ ~~`engine/workflow.py` legacy 相位机归档~~（已删除：2026-09-17 `d835bd8`，文件仅存 state/checkpoint-store）；benchmark 数据入库（历史趋势）；sandbox 开箱即用 profile 预设；Prompts/slash 结构化注册表。
- ⏳ 低优先技术债：`model_pricing` 抽独立模型 + 校验、`guard_content` 加 `source` 参数、Hook 事件集补齐（`UserPromptSubmit`/`Stop`/`SubagentStop`/`PreCompact`）、readline 在 Windows 的降级方案、firejail/WinJob 不可用的 CLI banner 提示、sandbox profile 参数合法性校验、`skill_update` 遇富正文技能拒绝改写。

### 7.4 已决策关闭（不再排期）

- 全局/home 级 MCP 注入签名入口（won't do；项目级 `.heagent/injection_signatures.json` 已交付）。
- 把 MCP Resources / Prompts 增强纳入必要开发范围（MCP 后续不作必要功能）。
- 业务数据整合母规划 spec（`spec-business-data-integration.md` 文件 2026-09-15 已删除）。
- 2026-09-18 复核确认**已闭合、不再列为待办**：bmad-build Step 07 `max_iterations`（E41-D6）、GUI `/goal` 收口（E41-D7）、goal 跨进程锁（E41-D5）、凭证 deny 项目级入口（F-D1）、沙箱资源/高级参数/per-tool 粒度（S-D4..D6）、`agent/loop.py` C901（已裁定接受）、`RoleSpec.sandbox_profile` 死字段（原 A5，取删除方向）、沙箱进程数限额（原 A6，`SANDBOX_NPROC_LIMIT` + WinJob 常量修正）。

---


---

## 维护规则（历史区）

> 本文是历史记录：内容为已发生事实的存档，日常不再修改，勘误以追加注记方式补在条目尾部，不改正文。
> 活动项写入根目录 open-items.md；当前状态与 epic 总目录写入 epic-overview.md（均 2026-11-15 定名）；Epic 级闭合条目按归属周期进 epics/<周期>/deferred-work.md，不在本文重复建档。
