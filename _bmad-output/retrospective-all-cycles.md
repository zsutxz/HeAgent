# HeAgent 全周期综合回顾

> 生成: 2026-07-22（**2026-09-15 扩充**：补周期 8–15 / Epic 24–47 速览；**2026-09-18 修订**：新增「五、待完成工作」，修正 6 处已闭环却仍列为待办的表述，指标刷新至 2026-09-18；2026-09-20 补录 §1b 自学习闭环速览并统一 §3 编号口径；**2026-09-22 补录 §15 架构优化周期**——非 BMad 流程的 6 阶段周期，指标刷新至 2026-09-22；**2026-09-24 补录 §16（Epic 48–50 网络入口三周期）**，覆盖与指标刷新至 2026-09-24）
> 覆盖: Epic 1–50 + S1–S4，**19 个周期**（**54 个 Epic 条目** = Epic 1–50 + S1–S4；另含架构优化周期 Phase 0–5，非 BMad 流程）
> 基准: **2061 passed / 9 skipped / 18 deselected**（2026-09-22 实测）、ruff / mypy clean、覆盖率 **90.88%**（gate 87）
>
> 归档更新：2026-09-14 已完成实现 spec 按 Epic 40 / Epic 47 归档；2026-09-15 `patches/` 目录解散（补丁 spec 按归属 epic 归档）、跨周期 deferred 台账按 epic 归并。
> **口径说明**：1.1–1.6 为 2026-07-22 的正式回顾；**1.7–1.14 是 2026-09-15 补录的速览**（这 8 个周期的 `epic-*-retrospective` 在 sprint-status 中多为 `optional`，未做正式回顾，明细见各周期目录与 `consolidated-overview.md` 十二）。**2026-09-18 更新**：36、37、40、41、42 已补做正式回顾（5 份 `retrospective-epic-NN.md`），`sprint-status.yaml` 的状态字段仍为 `optional`。**2026-09-24 更新**：§16 为 Epic 48–50 速览——**48 有正式回顾**（`epics/epic-48-TCP网络接口周期/retrospective-epic-48.md`，2026-09-23 补做）故按其摘录；**49 / 50 仍为 `optional`**（50 尚 `in-progress`），故按交付记录与 `reviews/` 产物摘录并标注来源。

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

### 16. 网络入口三周期（Epic 48–50）· 2026-09-22 – 2026-09-24

> **来源（逐条可查，不做推测式回顾）**：**Epic 48** 按其正式回顾 `epics/epic-48-TCP网络接口周期/retrospective-epic-48.md`（2026-09-23 补做）摘录；**Epic 49 / 50 的 retrospective 仍为 `optional`**（50 尚 `in-progress`），故按其交付记录、`epics/epic-49-HTTP网页访问周期/`、`epics/epic-50-网页控制台周期/` 与其 `reviews/` 产物摘录。状态口径以 `sprint-status.yaml` 为准。

| 维度 | 要点 |
|------|------|
| 交付 | **Epic 48 · TCP 网络接口（2026-09-22 建立并同日交付，6 story）**：`network/protocol.py`（请求/成功/失败模型 + 黄金 JSONL）+ `network/tcp_server.py`（`asyncio.start_server` 生命周期）+ `cli_tcp.py`（`TcpAgentHandler` / `build_server_config` / `tcp-server` 子命令）+ `network/exposure.py`（回环判定单点）；`network/` 运行期不依赖 `cli` / `agent` / `providers` / `engine`。**Epic 49 · HTTP 网页入口（2026-09-23，6 story）**：`network/http_*` + `cli_http.py` + 包内 `web/`（自启动监听 / 就绪门禁 / SSE 流式运行与取消重连 / Host-Origin 同源防线 / 安全响应头 / 静态资源白名单）。**Epic 50 · 网页控制台（2026-09-23 建立 → 09-24 实现，7 story 均 `review`）**：工作区一等化 + 项目注册表 + 会话持久化与会话 API + 配置四层来源与只读面板 + 闸门约束下的项目 `.env` 保真写（备份 / 冲突 / 审计）+ 两栏 UI 与真实浏览器验收。 |
| 难点 | 协议 / 传输层与 agent 彻底解耦（`network/` 运行期零反向依赖，被架构契约测试钉住）；**「非等待式」是限额的语义要求而非实现细节**（`Semaphore` 无 `try_acquire` ⇒ 限额退化成排队，名额记账必须用幂等集合，整数计数会在迟到任务上减成负数）；**三个危险默认值被实测证伪**（在途限额 / `click.FloatRange` 放行 `nan`·`inf` / 裸 `logger.*` 抛异常会把 `agent_error` 改写成 `server_error`）；相近命名通道必须显式区分（TCP JSONL ≠ `rollout.jsonl`）；只有真浏览器 + 计算样式才看得见的缺陷（作者级 `display` 压过 `hidden` 属性，且 `node.click()` 绕过命中测试）。 |
| 做对 | `close()` 坚持「有界返回 + warning + 结算登记」（无法强杀时如实写进 docstring，而非假装干净）；`_safe_log` 单点收口 + 注入式测试（Epic 48 共 10 个变异体全部精确变红后按 sha256 逐字节还原）；配置 / 协议各自唯一读取点（`tcp_*`、`HTTP_*`）；收口分两轮（先实现、后收口）并把评审发现当场分成「已修 / 未修如实登记」两栏；Epic 50 写通道沿用全项目纪律（fail-closed 校验 + 备份 + 审计 + 冻结边界 + 前端不硬编码键名）。 |
| 改进（2026-09-24 复核） | ① **Epic 48 回顾自己点名的「5 条缺口只进 `frame.md`、未进活动台账」已处理**——2026-09-23 补登活动台账，其中「运行栈日志非观测故障免疫」「入口日志未脱敏」当日闭合（**Z-D10 / Z-D11**，2026-09-24 已按归属 epic 回填 `epics/epic-48-TCP网络接口周期/deferred-work.md`），「TCP 入口不写 rollout」仍在活动区（**A7**）。② **Epic 49 / 50 的 retrospective 仍未补做**（`optional`；50 尚 `in-progress`）——宜按 Epic 48 先例在收口时一并补登，避免重复「交付时才补做」。③ Epic 50 两轮收口评审的发现被如实分成两栏：**3 条已闭合**（`Z-D13` / `Z-D14` / `Z-D15`，2026-09-24 回填 `epics/epic-50-网页控制台周期/deferred-work.md`）与 **7 条仍开**（活动台账 **A8~A14**，其中 **A11「非回环运行姿态 + cron 跨会话后置执行」标 `blocked` 待人裁决**）。④ 立场不变：三个入口**都不是安全边界**（无认证 / 无 TLS；回环判定与启动告警只是提示），须 OS 级沙箱兜底。 |

---

## 二、跨周期模式：做对了什么

| # | 模式 | 证据 |
|---|------|------|
| 1 | **协议优于实现** | BaseProvider Protocol、@tool 装饰器、Middleware 管道——新增模块零改动核心 |
| 2 | **deferred 编号化** | DP-4 等「暂不做」决定跨文档引用 (CLAUDE.md/frame.md/architecture.md)，防遗忘 |
| 3 | **「不成立」关闭模式** | SubAgent 竞态误判经核实关闭+回归测试锁定假阴性——比硬修不存在的问题更有价值 |
| 4 | **依赖最小化** | 手写 cron 解析器避掉 croniter、文件锁全 stdlib——NFR 贯彻始终 |
| 5 | **增量保持干净** | P5+engine 叠加式不动契约、DI 注入不篡改 AgentLoop 签名 |
| 6 | **YAGNI 克制** | MCP 2 transport 不抽 Protocol、不新建异常/重试、annotations 透传不裁决 |
| 7 | **防御纵深意识** | 所有安全相关组件明确标注「非真正边界，须 OS 级沙箱兜底」 |
| 8 | **分层门禁** | 本地 88/CI 90 coverage、bandit -ll 不阻塞 CI——差异化约束不互锁 |
| 9 | **优雅降级模式** | Firejail/WinJobBackend 不可用→warn+Passthrough，不 crash、不中断 |
| 10 | **对称性审查** | send/stream、enter/exit、kill/wait——成对路径互相对照补齐 |
| 11 | **方法论与机制分离** | `/goal` / 声明式工作流：流程规则归 Markdown（`.heagent/skills/he-goal/workflow.md` + 角色 SKILL.md，人可直接改），确定性边界归代码——工作流演进零代码改动 |
| 12 | **诚实门（honest gate）** | 能力「未真正生效」时宁可不报：`<shell-workspace>` 仅在真实后端就绪时注入；围栏 / 沙箱一律标注 defense-in-depth，不制造「已安全」假象 |

---

## 三、跨周期模式：可改进什么

> **2026-09-18 逐条复核 + 2026-09-24 复核**：下表 10 条已按当前代码与台账逐条核对，标注**仍开 / 部分解决 / 已修复 / 已裁定接受**；逐条证据与完整待办清单见 `consolidated-overview.md` §17.4（本节只留结论，不复制正文）。

| # | 模式 | 现状 |
|---|------|------|
| 1 | **安全边界诚实度** | **长期基调（非待办）**：命名/文档应持续降低「安全」期望，各文档已统一标注 defense-in-depth |
| 2 | **回顾不及时** | **仍开**（2026-09-24 复核）：**17 个 epic 的 retrospective 仍为 `optional`**（25-28 / 36-39 / 40 / 41 / 42 / 43-46 / **49 / 50**）；其中 36、37、40、41、42 已于 2026-09-18 补做、**Epic 48 于 2026-09-23 补做**，余 12 个未补做 |
| 3 | **静默降级** | **仍开**：firejail / WinJob 不可用仅 `logger.warning` + 降级 Passthrough，无 CLI banner 或首次加载提示——落点见 `consolidated-overview.md` §17.4-D（原此处引的 `tools/sandbox.py:423` 已随该模块包化失效） |
| 4 | **编号冲突** | 已 2026-07-23 统一编号空间，现无冲突 |
| 5 | **复杂度接受** | **已裁定接受**：`run_stream` 的 `noqa: C901` 有实测依据（抽出共用步骤后仍 17 > 15），理由已写入 `agent/loop.py:404,418` docstring——不再作为待拆分项 |
| 6 | **可观测缺口** | **部分改善（2026-09-22）**：事件契约 v2 落地（provider/tool/run/workflow 耗时 + error_kind 失败分类进事件流）；仍开：`S4-1` emit 事件仍 `skipped`（`engine/executor.py` 无 `sandbox_backend` / `sandbox_pid`）；benchmark 数据仍不入库（阈值入口已建：`--benchmark-compare-fail`，基线 autosave 本地） |
| 7 | **内置预设缺失** | **部分解决**：`SANDBOX_PROFILES`（2026-09-17）已可声明 `--seccomp`/`--caps` 等，但无开箱即用预设库；cron 仍无常见模板 |
| 8 | **扩展点不足** | **部分解决**：`slash.py` 已是注册表驱动；CLI 入口仍最小 `startswith("/")` 分发（`cli.py:544,714`） |
| 9 | **规划产物滞后于交付** | **仍开**（2026-09-18 实测）：6 个 36-39 story 的 frontmatter 仍为 `backlog`、45-1/45-2 无 story 文件 |
| 10 | **跨进程互斥缺位** | **已修复**（2026-09-17）：goal 跨进程 `file_lock`（E41-D5，`855d135`）；在途记录续租（E47-D1，`cc8cb3f`）——剩余仅「施动者未唯一归因」（LOW） |

---

## 四、指标总结

| 指标 | 数值 |
|------|------|
| 总 Epic 数 | **54**（Epic 1–50 + S1–S4），分属 **19 个周期**（18 个 BMad 周期 + 1 个架构优化） |
| 总 Story 数 | **101 个 story 文件（28 个 `stories/` 目录）**（2026-09-24 按 `_bmad-output/**/stories/` 全深度实测；原记 82 / 25 的计数口径未留档）+ quick-dev 直接执行项（Epic 29–35 等无独立 story 文件） |
| 总测试数 | **2061 passed / 9 skipped / 18 deselected**（2026-09-22；deselect = integration + benchmark） |
| 覆盖率 | **90.88%**（gate 87；`scripts/quality_gate.py` 五门：goal smoke / 回归+覆盖率 / ruff check / ruff format / mypy） |
| 代码行数 | ~55,600（`src/` 25,768 + `tests/` 29,794，2026-09-22 计数；130 / 106 个 `.py`） |
| 外部依赖 | 核心 5（openai / anthropic / pydantic / pydantic-settings / mcp）+ 可选（tiktoken 真实 tokenizer；textual GUI） |
| 开发周期 | 2026-05-26 → 2026-09-24（**121 天**） |

---

## 五、待完成工作（2026-09-24 复核）

> **权威来源**：活动（未闭合）条目 = `_bmad-output/implementation-artifacts/deferred-work-archive.md`；Epic/Story 状态 = `_bmad-output/sprint-status.yaml`；安全缺口 = `docs/frame.md` 五。逐条证据与「已闭环却仍被列为待办」的修正表见 `consolidated-overview.md` §17.4。

### 5.1 活动台账未闭合（14 条，**索引**）

> 正文、编号与「触发条件 / 严重度理由 / 冻结边界」一律以 `_bmad-output/implementation-artifacts/deferred-work-archive.md` 的**活动区**为准（2026-09-24 起本表只做导航、不再复制；编号 = 台账条目顺序），逐条摘要另见 `consolidated-overview.md` §17.4-A。
>
> **旧编号对照**：本条 2026-09-18 版列 A1~A4（TOCTOU / MCP stdio / cli 拆分 / 路径级审批）；新编号前三者不变，**路径级审批移到 A6**。原 A5（`RoleSpec.sandbox_profile` 死字段）与 A6（沙箱进程数限额）已于 2026-09-18 闭合——A5 取删除方向，A6 新增 `SANDBOX_NPROC_LIMIT` + 修正 WinJob `JOB_OBJECT_LIMIT_PROCESS_TIME` 常量（原误写 `0x8` 即 ACTIVE_PROCESS 位）；闭合档案见台账 **Z-D8 / Z-D9**。

### 5.2 纪律类滞后（非代码，2026-09-18 实测）

- 6 个 36-39 story 的 frontmatter 仍为 `status: backlog`（`36-1`/`36-2`/`36-3`/`37-1`/`38-1`/`39-1`）。
- `45-1` / `45-2` 无 story 文件（该 epic 仅 `45-3`）；`spec-45-3` / `spec-46-1` 已在归档提交中删除或改名。
- **17 个 epic 的 retrospective 状态仍为 `optional`**（25-28 / 36-39 / 40 / 41 / 42 / 43-46 / **49 / 50**）；其中 36、37、40、41、42 已于 2026-09-18 补做、**Epic 48 已于 2026-09-23 补做**，余 12 个未补做（Epic 50 尚 `in-progress`）。
- `S4-1`（executor emit `sandbox_backend` + `sandbox_pid`）仍 `skipped` —— 沙箱执行轨迹不可追溯。
- `_bmad-output/README.md:13` 仍描述 `implementation-artifacts/` 含 `deferred-work.md` 与母规划 spec——两者均已不存在（现为 `deferred-work-archive.md`；**2026-09-20 已修正该描述**）。

### 5.3 路线图与技术债候选（逐条已核实仍开）

- 🔜 **生产化**：PyPI 发布、Docker Hub 镜像、CI release workflow（版本 `0.6.2`；`.github/workflows` 只有 `ci.yml` + `codeql.yml`）。
- ⏳ ~~`engine/workflow.py` legacy 相位机归档~~（已删除：2026-09-17 `d835bd8`，文件仅存 state/checkpoint-store）；benchmark 数据入库（历史趋势）；sandbox 开箱即用 profile 预设；Prompts/slash 结构化注册表。
- ⏳ 低优先技术债：`model_pricing` 抽独立模型 + 校验、`guard_content` 加 `source` 参数、Hook 事件集补齐（`UserPromptSubmit`/`Stop`/`SubagentStop`/`PreCompact`）、readline 在 Windows 的降级方案、firejail/WinJob 不可用的 CLI banner 提示、sandbox profile 参数合法性校验、`skill_update` 遇富正文技能拒绝改写。

### 5.4 已决策关闭（不再排期）

- 全局/home 级 MCP 注入签名入口（won't do；项目级 `.heagent/injection_signatures.json` 已交付）。
- 把 MCP Resources / Prompts 增强纳入必要开发范围（MCP 后续不作必要功能）。
- 业务数据整合母规划 spec（`spec-business-data-integration.md` 文件 2026-09-15 已删除）。
- 2026-09-18 复核确认**已闭合、不再列为待办**：bmad-build Step 07 `max_iterations`（E41-D6）、GUI `/goal` 收口（E41-D7）、goal 跨进程锁（E41-D5）、凭证 deny 项目级入口（F-D1）、沙箱资源/高级参数/per-tool 粒度（S-D4..D6）、`agent/loop.py` C901（已裁定接受）、`RoleSpec.sandbox_profile` 死字段（原 A5，取删除方向）、沙箱进程数限额（原 A6，`SANDBOX_NPROC_LIMIT` + WinJob 常量修正）。

---

