# HeAgent 迭代开发指南与历程

> 这份文档回答两件事：**项目是怎么一步步迭代到现在的**（历程），以及**怎么继续迭代**（流程）。架构看 [`frame.md`](frame.md)，愿景看 [`design.md`](design.md)，本文只讲「迭代」这一维度。

## 这份文档的位置

| 文档 | 视角 | 回答 |
|------|------|------|
| `design.md` | 产品 | 为什么要做、目标与非目标 |
| `frame.md` | 架构 | 现在的实现怎么工作 |
| **`iteration.md`**（本文） | 工程 | 怎么迭代过来的、怎么继续迭代 |

`_bmad-output/` 是各周期的原始产物（brief/prd/epics/stories），是本文历程章节的事实来源之一；当本文与 `_bmad-output/` 或代码冲突时，以代码为准。

---

## 一、迭代模型（怎么继续迭代）

HeAgent 用 **BMad Method** 驱动迭代，组织单元是「**周期（Cycle）**」。一个周期 = 一个独立的目标集（一组 FR），产出自己的一套规划文档。

### 1.1 四类周期

| 周期类型 | 触发 | 产物目录 | 编号空间 |
|----------|------|----------|----------|
| **主线周期** | 新产品方向 / 大功能集 | `_bmad-output/<cycle>/`（brief→prd→architecture→epics→stories） | Epic 沿主线编号递增 |
| **集成周期** | 接入外部系统（如 MCP） | 同上，独立 brief/prd | Epic 编号延续主线 |
| **补丁周期** | 计划外技术债 / 缺陷 | `_bmad-output/patches/`（补丁 spec）+ 各周期 `deferred-work.md`（已闭合项按归属 epic 归档） | spec 文件，不占 Epic 编号 |
| **epic 外增量** | 架构演进（如 engine 治理层） | 直接落代码 + `frame.md` 记录 | 按 P0/P1… 分批 |

### 1.2 历史规划周期工作流

下面是历史规划产物采用的周期级顺序；它解释 `_bmad-output/` 的目录结构，不等于当前 `/goal` 的运行时步骤。
当前运行时工作流见 [`workflow_intro.md`](workflow_intro.md)。

每个历史周期按此顺序推进，每步对应一个 BMad skill（`bmad-*` 前缀）：

```
brief  →  prd  →  architecture  →  epics  →  stories  →  quick-dev  →  code-review
 产品意图   功能需求  技术架构         拆 epic      拆 story      执行实现      对抗式审查
```

1. **brief**（`bmad-product-brief`）：产品意图与边界，决策记入 `*-decision-log.md`。
2. **prd**（`bmad-prd`）：功能需求（FR/NFR）。
3. **architecture**（`bmad-architecture`）：技术架构与冻结决策。
4. **epics**（`bmad-create-epics-and-stories`）：FR → Epic 拆分 + 覆盖矩阵。
5. **stories**（`bmad-create-story`）：Epic → 可执行的 story（含 AC）。
6. **quick-dev**（`bmad-quick-dev`）：按 spec 实现（见 1.3）。
7. **code-review**（`bmad-code-review`）：分层对抗式审查。

> `sprint-status.yaml` 跟踪每个 story 的状态流转：`backlog → ready-for-dev → in-progress → review → done`。

### 1.3 历史 Story 执行：quick-dev + spec 冻结

历史 quick-dev 是**基于 spec 的单会话执行**：

- 每个 story / 缺陷 / 变更先冻结成一个 **spec**（明确做什么、不做什么的边界），再实现。
- **一会话一 spec**：完整 spec 执行接近单会话 token 上限，多个缺陷要拆成多次会话分别执行（参见记忆 `bmad-quickdev-budget-per-spec`）。
- spec 边界之外的发现 → 不就地扩展，而是记入 `deferred-work.md`（活动台账 `_bmad-output/implementation-artifacts/deferred-work.md`；见 1.4）。

### 1.4 技术债 deferral 机制

迭代中发现的、**超出当前 spec 冻结范围**的问题，走 deferral，不悄悄塞进当前改动：

1. **发现**：code-review 的 edge case hunter / blind hunter 发现。
2. **分类**：`fix now`（当前 spec 内修）/ `defer`（记入 deferred-work）。
3. **记录**：写入 `_bmad-output/implementation-artifacts/deferred-work.md`（活动台账，append-only），含触发条件、严重度、冻结边界说明、建议修法。
4. **收尾**：后续开专门 spec 处理，修完写 `Resolution` 段关闭；**闭合后按归属 epic 归档**到 `_bmad-output/epics/<周期>/deferred-work.md`（保留结论、证据与 commit 指针，不保留原始长文历史）。

> **已闭合项归档（2026-09-15 整理）**：原跨周期台账 `_bmad-output/patches/_meta/deferred-work.md` 的条目已全部闭合，按归属 epic 归并进各周期 `deferred-work.md`（`epic-01-10-主线规划周期`、`epic-11-18-MCP集成周期`、`epic-S1-S4-沙箱硬化周期`、`epic-40-沙箱会话化周期`、`epic-41-目标驱动开发周期`、`epic-47-声明式BMad敏捷工作流周期`），原台账随之退役并删除。条目索引见 `consolidated-overview.md` 11.1。

### 1.5 sprint-status 维护规则

- **Epic 编号延续主线**：新周期自称 Epic 1-N 会撞主线编号，故延续主线编号递增（MCP 周期 = Epic 11-13，MCP V2 周期 = Epic 15-18）。
- **story key 须匹配 `epic-N-M` pattern**：`sprint-status` skill 校验 key 格式，不能用自定义前缀（如 `mcp-`）。
- **MCP 周期映射**（2026-08-18 三目录合并为 `_bmad-output/epics/epic-11-18-MCP集成周期/`）：sprint-status 的 Epic 11-13 = `epics.md` 阶段一内部 Epic 1-3；Epic 14 = `epics.md` 阶段二；Epic 15-18 = `epics.md` 阶段三内部 Epic A/B/C + 内置工具扩展。
- **retrospective 字段**：每个 epic 配 `epic-N-retrospective`，状态 `optional`（可做不做）或 `done`（已完成）。
- **单一权威（2026-07-23）**：全周期 sprint-status 统一在 `_bmad-output/sprint-status.yaml`，旧文件保留作为只读归档。

---

## 二、迭代历程（怎么走到现在）

### 2.1 主线周期 · Epic 1-10

**Epic 1-5（MVP，FR-1~19）** —— 来源 `_bmad-output/epics/epic-01-10-主线规划周期/epics.md`：

| Epic | 主题 | FR |
|------|------|----|
| 1 | 项目基础设施与 LLM 通信 | FR-1~5, 19 |
| 2 | 自主 Agent 核心循环 | FR-6~9, 14 |
| 3 | 对话持久化与上下文管理 | FR-13, 15 |
| 4 | 自学习记忆系统 | FR-10~12 |
| 5 | 多 Agent 并行编排 | FR-16, 17 |

**Epic 6-10（自学习闭环扩展，FR-20~24）** —— 来源 `_bmad-output/epics/epic-01-10-主线规划周期/epics-self-learning.md`，补齐从「被动工具」到「主动学习者」的能力：

| Epic | 主题 | FR |
|------|------|----|
| 6 | Context Files 自动加载 | FR-20 |
| 7 | SOUL.md 人格系统 | FR-21 |
| 8 | Memory Nudge 记忆提醒 | FR-22 |
| 9 | Skill Curator 技能策展 | FR-23 |
| 10 | Cron 定时调度 | FR-24 |

> MVP 范围内的 FR-18（MCP 工具发现）当时标注「延后」，后由 MCP 周期承接。

### 2.2 MCP Client 集成周期一 · Epic 11-13

来源 `_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段一，原 `mcp-client/`，2026-08-18 合并），独立 brief/prd/architecture/epics：

| Epic | 主题 |
|------|------|
| 11 | MCP 工具桥接（FR-1~8：配置加载、tool↔ToolSchema 映射、ClientManager 生命周期、CLI 装配） |
| 12 | GitHub 只读验收（FR-9：E2E 锁定真实工具名） |
| 13 | 安全边界与开源可用（FR-10/11：安全声明覆盖 MCP 不可信边界 + 开源文档） |

### 2.3 MCP Client V2 集成周期二 · Epic 15-18

来源 `_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段三，原 `mcp-client-v2/`），2026-07-17 启动。延续主线编号 15-18（映射 epics.md 的 Epic A/B/C + 内置工具扩展）：

| Epic | 主题 | 状态 |
|------|------|------|
| 15 | 写操作治理 — MCP 工具危险分级的确定性闸门（FR-A1~A7，AD-1/2/3） | **已完成** — 15-1 annotations 数据管线 + 15-2 policy 注解闸门 + 15-3 零回归确定性 + 15-4 安全声明同步已全部 `done` |
| 16 | Resources on-demand 发现与读取（FR-B1~B4，AD-4/5/6） | **已完成** — 16-1 sessions 查找表 + 16-2 list_resources 桥接工具 + 16-3 read_resource + guard_content 围栏 + 16-4 安全声明同步已全部 `done` |
| 17 | Prompts 交互式协商（FR-C1~C4，AD-7/8/9） | **已完成** — 17-1 manager prompts 入口 + 17-2 slash 命令调度 + 17-3 渲染守卫 + 17-4 测试已全部 `done` |
| 18 | 内置工具扩展（git 工具 + path safety 集成） | **已完成** — 18-1 git-status-diff + 18-2 git-log-blame + 18-3 path-safety-integration + 18-4 tests-docs 已全部 `done` |

### 2.4 Sandbox 硬化周期 · Epic S1-S4

来源 `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/`，2026-07-20 启动。Sandbox 后端硬化，含 firejail profile 映射、降级、配置入口、Linux 进程组 kill、workspace 隔离：

| Epic | 主题 | 状态 |
|------|------|------|
| S1 | profile 映射 + contextvar 注入 | **已完成** |
| S2 | firejail 可用性降级 + 配置入口 | **已完成** |
| S3 | Linux 进程组 kill + workspace 隔离 | **已完成** |
| S4 | 安全声明同步 | **已完成** — S4-1 emit 事件被跳过，S4-2 安全声明同步 `done` |

### 2.5 健壮性与质量硬化周期 · Epic 19-20

来源 `_bmad-output/epics/epic-19-20-健壮性硬化周期/`，2026-07-21 启动。跨进程文件锁、Cron 范围表达式、WinJobBackend、覆盖率 89%→90%：

| Epic | 主题 | 状态 |
|------|------|------|
| 19 | 健壮性硬化（FR-A1~A5） | **已完成** |
| 20 | 质量工程化（FR-C1~C6） | **已完成** — 覆盖率 89%→90%，922 测试全绿 |

### 2.6 质量工程深化周期 · Epic 21-24

来源 `_bmad-output/epics/epic-21-24-质量工程周期/`，2026-07-22 启动。Coverage 工程化、Benchmark 重构、Docker 硬化、CI 效能/安全左移：

| Epic | 主题 | 状态 |
|------|------|------|
| 21 | Coverage 工程化 | **已完成** |
| 22 | Benchmark 重构 | **已完成** |
| 23 | Docker 硬化 | **已完成** |
| 24 | CI 效能与安全左移 | **已完成** |

### 2.7 GUI 终端界面周期 · Epic 25-28

来源 `_bmad-output/epics/epic-25-28-GUI界面周期/`，2026-07-23 启动。Textual 终端界面，含流式聊天、工具可视化、管理面板、可观测性：

| Epic | 主题 | 状态 |
|------|------|------|
| 25 | 流式聊天 — 最小可跑（FR-G1~G6） | **in-progress** — 25-1/2/3 ready-for-dev |
| 26 | 工具可视化 + 斜杠命令（FR-G7~G14） | backlog |
| 27 | 管理面板（FR-G15~G19） | backlog |
| 28 | 可观测性（FR-G20~G24） | backlog |

### 2.8 补丁周期 · 技术债收尾

`_bmad-output/patches/` 扁平存放计划外补丁 spec；遗留项活动台账为 `implementation-artifacts/deferred-work.md`，条目闭合后按归属 epic 归档到各周期 `deferred-work.md`。已交付：`3-3-token-counter`（文件 2026-09-15 已删除）、`5-1-subagent-context-injection`、`epic-5-context`、`p0-provider-hardening`、`fr3-mcp-auto-unregister`（FR-3 MCP 运行时断连 auto-unregister）。**sandbox 健壮性系列（2026-07-09~10）**：`spec-engine-sandbox-backend`（`CommandRunner` 抽象 + code review 三修）、`spec-sandbox-timeout-validation`（timeout 正整数校验）、`spec-sandbox-cancel-signal-preservation`（CancelledError 不吞取消信号）、`spec-sandbox-reap-robustness`（reap 保护 + wait 硬上界 + kill/wait 解耦）。**关停硬上界三件套（2026-07-10~11，同构）**：`spec-mcp-shutdown-timeout`（MCP `__aexit__`）、`spec-cron-stop-timeout`（`CronScheduler.stop`）、`spec-deferred-low-cleanup`（deferred-work 收尾）。**DP-4 两半**：`spec-dp4-mcp-safety-guard`（执行前工具名拦截）、`spec-dp4-mcp-result-guard`（返回内容启发式围栏）。另有两份轻量回顾：`retrospective-engine-p5.md`、`retrospective-p0-tech-debt.md`。**台账归档（2026-09-15）**：`patches/_meta/deferred-work.md` 的条目已全部闭合，按归属 epic 归并进各周期 `deferred-work.md` 后原台账退役并删除（见 1.4；活动遗留项仍在 `implementation-artifacts/deferred-work.md`）。

### 2.9 engine/ 增量 · epic 外 P0-P5

运行时治理层（`PolicyEngine` + `ToolExecutor` + `store/ledger/observability`）按 P 批演进，不挂 Epic 编号，进度记入 `frame.md` 4.12：

| 批次 | 内容 |
|------|------|
| P0 | loop engine runtime 落地 |
| P1/P2 | 多 agent 角色化 + supervisor 编排 |
| P3/P4 | checkpoint-resume + 工具执行幂等 |
| P5-3/P5-4/P5-5 | 结构化子任务结果（`SubTaskOutcome`）+ `parent_run_id` 树形聚合 + resume 流式版 |
| P5-1/P5-2 | **2026-07-21 已交付**：schema 级工具白名单过滤（`AgentLoop._get_tools()`）+ `SubAgent` 可选 `window_reset` 参数 |
| sandbox 后端 | `execute_in_sandbox` 接 `CommandRunner` 抽象（`tools/sandbox.py`）：默认 Passthrough，可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），经 `RuntimeSlot` 注入 |

### 2.10 迭代时间线（git log 提炼）

| 时间 | 里程碑 |
|------|--------|
| 2026-05-26 | baseline 规划冻结（epics/architecture/prd） |
| 2026-06-08 | 自学习闭环 Epic 6-10 分解 |
| 2026-06-19~20 | P0 provider 技术债收尾 + MCP Client 集成周期（Epic 11-13） |
| 2026-06-21 | `_bmad-output/` 按周期重组 + 去日期化 |
| 2026-06-23 | engine P0 loop engine runtime 落地 |
| 2026-06-25 | engine P1-P5 同日集中落地（多 agent 角色化 + checkpoint-resume + 结构化结果/树形聚合/resume 流式）+ 新增 `design.md`；`frame.md` 4.2 对齐 engine 集成 |
| 2026-06-26 | bmad-method 6.8.0 → 6.9.0；`frame.md` 补 loop engine |
| 2026-06-29 | engine / agent 源码补详细中文注释；`loop.py` 968→797 行拆分（零回归）；新增 GitHub Actions 质量门禁 + pre-commit 钩子；epic-13 retrospective 完成 |
| 2026-07-01 | 收敛工作区路径围栏为 `resolve_under_root` 单一算法；FR-3 收紧（MCP 运行时断连 ping-watch auto-unregister）；engine 健壮性四件套（ledger/store I/O 全套 async 化、缓存命中复核 policy、持久化原子写 + 损坏 JSON 容错、lease-active 命中跳过重复执行） |
| 2026-07-08 | engine sandbox 接真实后端：`execute_in_sandbox` 经 `CommandRunner` 抽象（`tools/sandbox.py`）+ `RuntimeSlot` 注入，默认 Passthrough、可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界） |
| 2026-07-09 | sandbox 健壮性 D1/D3/D4：取消执行时 kill+wait 子进程修 `CancelledError` 泄漏；`timeout` 正整数校验（raise 非 clamp，fail-closed 拦 None/str/float/bool/nan）；firejail 测试保真度（returncode per-instance）；engine sandbox 后端 code review 三处修复 |
| 2026-07-10 | sandbox reap 鲁棒性收尾：`CancelledError` 清理不吞取消信号（D-1，`suppress(BaseException)`+裸 raise）+ reap 保护 + `wait` 硬上界（`_REAP_WAIT_TIMEOUT`）+ kill/wait 解耦（item 1/2/3）+ kill 块 `except` 收窄 `Exception`（不吞 KeyboardInterrupt）；DP-4 第二半——MCP 返回内容注入启发式围栏（`mapping.bridge_result` 标记透传，非真正边界）；MCP `__aexit__` 关停硬上界（transport close 挂死兜底） |
| 2026-07-11 | deferred-work 剩余 LOW 项收尾；`_await_shutdown` 二轮 `wait` 收窄为 pending 子集；`CronScheduler.stop` 关停硬上界（task 挂死兜底，与 MCP `__aexit__` 同构）——**三处同构关停硬上界补齐**；docs 同步 DP-4 过时表述 |
| 2026-07-12 | bmad 根除 gds/bmb 残留（uninstall + install --modules core,bmm） |
| 2026-07-14 | `.env` 优先级反转：同 key 冲突 `.env` 胜出（`init > dotenv > env > secrets`），系统环境变量退居兜底（仅填充 `.env` 未声明的键） |
| 2026-07-16 | compressor 切分不产生孤儿 TOOL 消息；三项代码审查必修修复（`loop.py` ExitStack bind 异常 / `sandbox.py` kill 块 / `mapping.py` 注入模式描述）；新增 `docs/code-review-conclusion.md`、`docs/learning.md` |
| 2026-07-17 | MCP Client V2 周期启动（Epic 14-16）；`ToolAnnotations` 数据模型 + `mapping.py` 透传管线（14-1）；`file_read` 新增 `offset`/`limit` 行范围参数 |
| 2026-07-17 | 模板方法重构 `run`/`run_stream`（解耦异步/同步路径）；`PolicyEngine` annotations 感知写操作闸门（14-2：destructive→审批 / readOnly→放行 / 缺省→fail-safe）+ 零回归测试 + 安全声明同步（CLAUDE.md 标注 annotations 不可信）；`_bmad-output/` 旧版 sprint-status 清理；CLI 版本 banner |
| 2026-07-17 | **Resources 桥接工具（Story 15-1/15-2）**：`_sessions` 查找表 + `_get_session` + `_handle_list_resources` 聚合 JSON 桥 + `_register_bridge_tool`（`readOnlyHint=True`）+ `_server_loop` 异常路径 session cleanup —— 14 个新测试，31/31 manager 测试通过，**全线 586/586 通过** |
| 2026-07-20 | **Sandbox 硬化周期（profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离）**——Epic S1-S4 全部 8 个 story 交付，新增 24 个 sandbox 专项测试，全量 751/751 通过 |
| 2026-07-21 | **Epic 19 完成**——覆盖率 89%→90%：新增 21 个专项测试覆盖 17 个模块，911 测试全绿，ruff 零错误。健壮性与质量硬化周期（Epic 18-19）全部交付。
| 2026-07-21 | **健壮性与质量硬化周期（Epic 18）**：跨进程文件锁（`persist.py` `lock=True` POSIX/Windows 平台自适应 + `EngineContainer.enable_file_locks`）+ Cron 范围表达式（`1-5`/`*/15`/`1-30/10`）+ `WinJobBackend`（Windows Job Objects 进程级隔离）+ 安全声明/文档同步——Epic 18 全部交付，新增 46 个专项测试（9 文件锁 + 27 cron + 10 WinJob），**全线 797/797 通过** |
| 2026-07-21 | **P5-1/P5-2 交付**：schema 级工具过滤 + SubAgent window_reset + CLI 阻塞缺口关闭（文档同步） |
| 2026-07-20 | **Resources 完成（Story 15-3/15-4）**：`guard_content` 提取为公共函数（供 `bridge_result`/`read_resource` 共用）+ `mcp__read_resource` 桥接工具 handler（`_handle_read_resource`，含 `server`/`uri` 参数 + `readOnlyHint`）+ 安全声明同步 + 配套测试（49 个 mapping + 46 个 manager 测试，**全线 607/607 通过**） |
| 2026-07-20 | **Prompts 桥接完成（Epic 16，Story 16-1~4）**：manager prompts 入口 + slash 命令调度 + 渲染守卫 + 测试——MCP V2 周期（Epic 14-16）全部 `done` |
| 2026-07-22 | **质量工程深化（Epic 21-24）**：coverage 工程化 + benchmark 重构 + Docker 硬化 + CI 效能/安全 + pre-commit 加固 + Ruff 扩展——全部 4 个 Epic、20 个 FR 交付，零业务代码改动，922 测试全绿 |
| 2026-07-22 | **全周期回顾完成**：`_bmad-output/retrospective-all-cycles.md` 覆盖全部 24 个已完成 Epic + S1-S4，所有 sprint-status 的 `epic-N-retrospective` 标记 `done` |
| 2026-07-23 | **GUI 终端界面周期启动**：BMad 规划冻结（brief→prd→architecture→epics），Epic 25-28 开始，流式聊天为当前焦点 |
| 2026-08-19 | **交互与可扩展层周期（Epic 29-35）全部交付**：审批闭环 / 会话恢复 / 斜杠命令 / Hooks / Plan Mode / 配置文件驱动角色 + 成本估算 / CLI 体验 + 技术债收尾——7 个 Epic、28 个 story、7 次提交，全量 1052 测试通过 |
| 2026-08-24 | **文件安全与凭证防护周期（Epic 36-39）全部交付**：凭证 deny（读+写）/ env scrubbing / 内部状态读 deny / 文档同步——4 个 Epic、6 个 story，全量 1135 测试通过 |
| 2026-09-14 | **工具调用可见性：CLI 显示「读写的文件 / 委派的子 Agent」**——新增 `tools/call_summary.py`（`summarize_tool_call`，纯函数、零 heagent 依赖，是该信息的唯一来源）；`StreamEvent` 新增 `tool_target`（`tool_call` 提前到执行前发出，长耗时工具实时可见）+ `tool_error`/`tool_name`（失败归因）；CLI 渲染 `[calling file_read → src/a.py]`、失败另起 `[failed shell]`（成功不再逐条 `[done]`——批次并发执行会挤成一串无主语标记）；TUI 聊天日志同步附摘要。**同日续作三件**：①`EngineEvent.target` 提为独立字段（日志按段渲染 `target=…`，不再埋进 `details`；`ToolExecutor` 的全部工具事件都带），GUI 事件日志屏同步；②`AgentLoop.active_tool`（在途批次摘要，批次结束/取消即清空）+ 状态栏 `🔧 …` 段，暂停/恢复行同时打印状态行，一眼看出卡在哪个工具；③`AgentLoop.tool_activity` run 级台账 + `cli_display.show_tool_activity`（单次模式跑完回显「读了哪些文件、跑了哪些命令」，同目标去重、超 20 条折叠）。**同日续作**：④CLI 提示行的 **shell 命令改为显示全文**（`_NO_TRUNCATE_TOOLS`：只折叠空白不截断——截断后无法判断「它到底跑了什么」，审查与审计场景信息损失最大），其余参数仍按 72 / 40 截断；⑤修掉 `call_summary` 兜底分支的**测试假绿**——`_BrokenArguments.__len__` 返回 0 使 `arguments or {}` 短路成空字典，损坏映射根本不被迭代，`except` 兜底（`call_summary.py:66-67`）从未被覆盖，改为 truthy 后该分支由真实异常路径覆盖。**同日复核修复 P2–P7**：⑥GUI 状态栏口径统一——`gui/bridge.py`（流式事件路径）原先只写裸工具名，与 `gui/observers.py`（引擎事件路径）的 `tool → target` 互相覆盖，现两条路径都走新增的 `call_summary.activity_label`（拼接唯一来源，先前四处重复的箭头拼接收敛为一处）；⑦GUI 失败不再画绿勾（抽出 `_render_tool_result`：按 `tool_error` 输出红叉并归因、成功仍绿勾），工具输出与 target 经 `rich.markup.escape`（`#chat-log` 是 `markup=True`，不可信文本里的 `[red]` 曾被当标记解释）；⑧`_TARGET_FIELDS` 删除三个**不可达表项**（file_write / git_diff / task_delegate 被 `_describe` 特殊分支抢先命中 → 改表不生效的死配置），并加参数化回归 `test_every_table_entry_is_reachable`（哨兵字段名）自动拦截未来新增的死表项；⑨`resume` 路径补上展示态重置（原先只在 `_init_new_run`，恢复分支提前 return 会跳过，状态栏/台账会残留上一段 run 的值）；⑩台账语义澄清为「调用尝试」（头部文案 + docstring + `loop.tool_activity` 注释，不再暗示「执行成功」）；⑪GBK 控制台图标降级——`🔧 ▶ ✔ ✘` 在 cp936 下均不可编码（实测），`cli_display._icon` 按 `sys.stderr.encoding` 降级为 ASCII，避免重定向到 GBK 日志时抛 `UnicodeEncodeError` 打断 run；⑫`docs/langchain-migration-feasibility.md` 纳入 docs/README 索引。93 个新测试，全量 1678 通过，覆盖率 89.62% |

### 2.11 交互与可扩展层周期 · Epic 29-35

来源 `_bmad-output/epics/epic-29-35-交互扩展周期/`（2026-08-19 启动并完成）。对照 Claude Code 补齐「面向使用者的交互与可扩展层」——审批、会话恢复、斜杠命令、Hooks、Plan Mode、自定义角色、成本追踪。全部复用既有基础设施（PolicyEngine / SessionStore / EventBus / RoleSpec / TokenUsage），`AgentLoop` 核心零侵入：

| Epic | 主题 | FR |
|------|------|----|
| 29 | 运行时审批闭环 | FR-A1~A5（`ApprovalHandler` 协议 + `APPROVAL_REQUIRED` 交互授权） |
| 30 | 会话恢复入口 | FR-B1~B3（`--continue`/`--resume`） |
| 31 | 斜杠命令系统 | FR-C1~C4（注册表 + 用户自定义命令） |
| 32 | Hooks 系统 | FR-D1~D4（PreToolUse/PostToolUse/SessionStart/End） |
| 33 | Plan Mode / 只读模式 | FR-E1~E4（readOnlyHint 白名单收敛） |
| 34 | 配置文件驱动角色 + 成本估算 | FR-F1~F4 |
| 35 | CLI 体验优化 + 技术债收尾 | FR-G1~G4（web_fetch guard_content / cron expr 诊断 / init --project / readline） |

详见 `_bmad-output/epics/epic-29-35-交互扩展周期/`（brief/prd/epics/retrospective）。

---

### 2.12 文件安全与凭证防护周期 · Epic 36-39

来源 `_bmad-output/epics/epic-36-39-文件安全防护周期/`（2026-08-24 启动并完成）。借鉴 hermes
`agent/file_safety.py` 的纵深防御设计，补齐凭证文件 deny（读 + 写）、凭证环境变量 scrubbing、
`.heagent/` 内部状态读 deny 三类防护：

| Epic | 主题 | FR |
|------|------|----|
| 36 | 凭证文件精确 deny（读 + 写） | FR-F1/F2 |
| 37 | 凭证环境变量 scrubbing | FR-F3 |
| 38 | `.heagent/` 内部状态读 deny | FR-F4 |
| 39 | 安全声明 + 文档同步 | FR-F5 |

详见 `_bmad-output/epics/epic-36-39-文件安全防护周期/`（brief/prd/architecture/epics/stories）。

---

## 三、经验教训（轻量 retrospective）

> 下面是从 `deferred-work.md`（原跨周期台账，2026-09-15 退役并删除）、`frame.md` 已知缺口、git log 反推的跨 epic 教训。
> **2026-07-22 更新**：全部 24 个已完成 Epic + S1-S4 的正式回顾已完成（产物 `_bmad-output/retrospective-all-cycles.md`），所有 sprint-status 的 `epic-N-retrospective` 均已标记 `done`。以下 10 条为跨周期课纲，详尽「做对/可改进」见全周期回顾。

1. **edge case hunter 会误判并发竞态**（Epic 5 / SubAgent）：deferred-work 第一条把「多协程访问共享 SkillStore」判为竞态，经核实不成立——`record_usage` 是无 `await` 的同步原子段，单线程 asyncio 下必然串行。**教训**：审查发现要核实是否真有 `await` 交错，加回归测试锁定不变量即可。
2. **异常包装要加守卫，避免双层重包**（Epic 1 / ProviderChain）：provider 源头包成 `ProviderError` 后，chain 的 `except` 又包一层。**教训**：`_wrap_error` 类入口加 `if isinstance(e, ProviderError): raise`；用 `__cause__` 链断言写回归测试。
3. **流式与同步路径要对称**（Epic 1）：`send()` 的 backstop 跟踪 `last_error`，`stream()` 版本一度漏了。**教训**：成对的 send/stream 实现要互相对照，补齐对称路径。
4. **安全边界必须诚实声明，不制造「更安全」假象**（Epic 13 / engine）：`SafetyGuard` 与 engine sandbox 都不是真边界。**教训**：安全相关代码注释里写明「非真正边界，须 OS 级沙箱兜底」，见 `CLAUDE.md` 文首声明。
5. **两种模式并存要标记冲突，而非折中**（engine / 工作区路径双重围栏，**已收敛**）：`PolicyEngine._validate_paths()` 与 `tools/path_safety.py` 曾两套围栏并存。**教训**：改其一须同步评估另一处，冲突在文档显式标出——后经收敛为共用 `resolve_under_root` 单一算法（两层有意纵深防御）解决（2026-07-01 commit `2ae99ed` 落地，`c7171ba` 同步 frame.md/CLAUDE.md 已知缺口）。
6. **评估结论要留依据**（engine P5-1/P5-2）：暂缓决策（D1/D4）把理由写进 `frame.md`，避免日后重做时忘记为何如此——P5-1/P5-2 后于 2026-07-21 反转交付，当初的取舍依据仍有助于理清演进。
7. **缓存命中仍须复核策略裁决**（engine / ExecutionLedger）：ledger COMPLETED 缓存命中后曾直接返回，未复核最新 policy——若 policy 收紧为 `BLOCKED` 仍返回缓存会绕过门禁。**教训**：缓存层与策略层交叉时，命中后仍须过一遍 policy（commit `84ee783`）；同理 lease-active 命中跳过执行，防并发/重入重复跑 handler（`c07f811`）。
8. **关停/清理路径必须有硬上界**（sandbox / MCP / cron，2026-07-09~11）：`_kill_and_reap` 的 `proc.wait()`、MCP `__aexit__` 的 transport close、`CronScheduler.stop` 的 task join 都是裸 `await`，遇不可中断 await 点（Linux D-state / 远端不 FIN / job 执行中）会无限阻塞，唯一调用方（CLI 退出路径）挂死需 OS SIGKILL。**教训**：凡 `task.cancel()` + `await` 的关停结构，`await` 必包 `asyncio.wait(timeout=N)`，超时记 ERROR 放弃——三处同构缺口同批补齐（`spec-sandbox-reap-robustness` / `spec-mcp-shutdown-timeout` / `spec-cron-stop-timeout`）。
9. **上下文切分要保证消息配对完整**（compressor，2026-07-16）：compressor 按预算切分历史时，切点若落在 TOOL 调用与其 TOOL 结果之间，会留下孤儿 TOOL 消息（有调用无结果），破坏 LLM 的 tool_use/tool_result 配对约束。**教训**：切分边界须以完整工具轮次（call+result）为不可分割单元。
10. **跨 task session 泄露要两面收尸**（MCP `_server_loop`，2026-07-17）：`_server_loop` 在 `__aenter__` 成功后登记 `self._sessions[name] = session`，但 `_discover_and_register` 失败时 `except` 处理器只 set ready 未 pop——`_sessions` 残留虚假 session，桥接工具据此注册，后续调用抛异常。**教训**：配对登记的清理点必须覆盖全部退出路径（`except` + `finally` 两面收尸），单靠 `finally` 不够——`finally` 仅清 `entered` 路径，`except` 段的 early return 漏了 `finally` 后的 `pop` 收尾。

---

## 四、路线图与下一步

**历史快照（2026-08-19）**：当时记录的 9 个开发周期（主线 Epic 1-10、MCP 11-18、Sandbox 硬化 S1-S4、健壮性/质量 19-24、GUI 25-28、交互与可扩展层 29-35）已全部交付；该日期的测试统计仅代表当时状态。

**当前状态（2026-09-08）**：后续文件安全、沙箱会话、目标驱动开发、BMad 技能包和声明式工作流周期已完成或有独立产物，状态以 [`_bmad-output/sprint-status.yaml`](../_bmad-output/sprint-status.yaml) 为准。当前 `/goal` 的可执行契约是 [`.heagent/workflows/workflow.md`](../.heagent/workflows/workflow.md)，维护说明见 [`workflow_intro.md`](workflow_intro.md)；`pytest --collect-only -q` 收集数以本地运行结果为准，质量门禁仍需在可写临时目录下运行。

**当前缺口**（详见 `frame.md` 第五章）：

- `SafetyGuard` / `path_safety` / engine sandbox 均非真边界，须 OS 级沙箱兜底。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），file/memory 等不受覆盖。

**下一步（候选，非承诺）**：

- ✅ **回顾**：截至 2026-08-19 的主线、MCP、Sandbox、健壮性/质量、GUI 和交互周期回顾已归档；后续周期的交付记录分散在各周期目录，不能将 `retrospective-all-cycles.md` 视为 Epic 36–47 的完整回顾。
- ⏳ **生产化**：PyPI 发布、Docker Hub 镜像、CI release workflow。
- 🔮 **可选增强**：多模态（vision）、Web API 服务端（均与 `design.md` 当前非目标冲突，需重新评估）；Hooks 增强（`UserPromptSubmit`/`Stop`/`SubagentStop` 事件、参数模板引擎）。

---

## 五、相关索引

### 2026-09-01：目标级工作流质量收口

Epic 43-44 的实现已完成，Epic 45.3 补齐了无网络两-story 冒烟、checkpoint/ledger/EventBus 审计证据、损坏状态显式失败测试，以及 `scripts/quality_gate.py` 统一质量门。Epic 46.1 完成 TOCTOU assessment，Epic 46.2 为资源读取增加 descriptor + `O_NOFOLLOW` 最终组件加固；中间目录竞态、可信导入 snapshot 与 OS sandbox 仍保留为后续工作。

- 架构权威：[`frame.md`](frame.md)（含 engine 模块 4.16、已知缺口第五章）
- 当前工作流：[`workflow_intro.md`](workflow_intro.md)（`.heagent/workflows/workflow.md` 为可执行契约）
- 产品愿景：[`design.md`](design.md)
- **全周期回顾**：[`_bmad-output/retrospective-all-cycles.md`](../_bmad-output/retrospective-all-cycles.md)
- 迭代原始产物：`_bmad-output/epics/epic-01-10-主线规划周期/`、`_bmad-output/epics/epic-11-18-MCP集成周期/`（原 mcp-client/ + mcp-v2-upgrade/ + mcp-client-v2/，2026-08-18 合并）、`_bmad-output/epics/epic-S1-S4-沙箱硬化周期/`、`_bmad-output/epics/epic-19-20-健壮性硬化周期/`、`_bmad-output/epics/epic-21-24-质量工程周期/`、`_bmad-output/epics/epic-25-28-GUI界面周期/`、`_bmad-output/epics/epic-29-35-交互扩展周期/`、`_bmad-output/epics/epic-36-39-文件安全防护周期/`、`_bmad-output/epics/epic-40-沙箱会话化周期/`、`_bmad-output/epics/epic-41-目标驱动开发周期/`、`_bmad-output/epics/epic-42-BMad技能包运行时周期/`、`_bmad-output/epics/epic-43-46-目标级工作流周期/`、`_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/`、`_bmad-output/patches/`
- **sprint 状态（单一权威）**：[`_bmad-output/sprint-status.yaml`](../_bmad-output/sprint-status.yaml)（持续更新，覆盖当前全部周期与 Epic）
- 技术债登记：活动台账 `_bmad-output/implementation-artifacts/deferred-work.md`；已闭合项按归属 epic 归档到 `_bmad-output/epics/<周期>/deferred-work.md`（原 `_bmad-output/patches/_meta/deferred-work.md` 已于 2026-09-15 退役并删除）
- 已产出 retrospective：`_bmad-output/retrospective-all-cycles.md`、`_bmad-output/epics/epic-11-18-MCP集成周期/retrospective-epic-13.md`、`_bmad-output/patches/_meta/retrospective-engine-p5.md`、`_bmad-output/patches/provider/retrospective-p0-tech-debt.md`
