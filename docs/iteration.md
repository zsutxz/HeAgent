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
| **补丁周期** | 计划外技术债 / 缺陷 | `_bmad-output/patches/` + `deferred-work.md` | spec 文件，不占 Epic 编号 |
| **epic 外增量** | 架构演进（如 engine 治理层） | 直接落代码 + `frame.md` 记录 | 按 P0/P1… 分批 |

### 1.2 主线 / 集成周期的标准工作流

每个新周期按此顺序推进，每步对应一个 BMad skill（`bmad-*` 前缀）：

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

### 1.3 Story 执行：quick-dev + spec 冻结

quick-dev 是**基于 spec 的单会话执行**：

- 每个 story / 缺陷 / 变更先冻结成一个 **spec**（明确做什么、不做什么的边界），再实现。
- **一会话一 spec**：完整 spec 执行接近单会话 token 上限，多个缺陷要拆成多次会话分别执行（参见记忆 `bmad-quickdev-budget-per-spec`）。
- spec 边界之外的发现 → 不就地扩展，而是记入 `deferred-work.md`（见 1.4）。

### 1.4 技术债 deferral 机制

迭代中发现的、**超出当前 spec 冻结范围**的问题，走 deferral，不悄悄塞进当前改动：

1. **发现**：code-review 的 edge case hunter / blind hunter 发现。
2. **分类**：`fix now`（当前 spec 内修）/ `defer`（记入 deferred-work）。
3. **记录**：写入 `_bmad-output/patches/deferred-work.md`，含触发条件、严重度、冻结边界说明、建议修法。
4. **收尾**：后续开专门 spec 处理，修完写 `Resolution` 段关闭。

> `_bmad-output/patches/deferred-work.md` 原 3 条（SubAgent 写竞态、ProviderChain 双层重包、流式 backstop 丢失上下文）均已收尾关闭——竞态经核实不成立（单线程 asyncio 下同步方法串行），另两项已修复。2026-07-01 FR-3 auto-unregister 评审另增 6 项 `defer`（pre-existing / spec 显式排除 / 非阻塞）：4 项已 Resolution 关闭（`__aexit__` 关停硬上界、handler 异常经 executor 兜底、`_unregister_all` 已是快照、测试保真度 a/b/c 补强），余 2 项保持现状（`_watch` 两个 `wait_for` 同名异义 / `except Exception` 过宽——待未来 MCP 重连场景再收窄）。

### 1.5 sprint-status 维护规则

- **Epic 编号延续主线**：新周期自称 Epic 1-N 会撞主线编号，故延续主线编号递增（MCP 周期 = Epic 11-13）。
- **story key 须匹配 `epic-N-M` pattern**：`sprint-status` skill 校验 key 格式，不能用自定义前缀（如 `mcp-`）。
- **MCP 周期映射**：sprint-status 的 Epic 11-13 = `epics-mcp-client.md` 内部的 Epic 1-3。
- **retrospective 字段**：每个 epic 配 `epic-N-retrospective`，状态 `optional`（可做不做）。

---

## 二、迭代历程（怎么走到现在）

### 2.1 主线周期 · Epic 1-10

**Epic 1-5（MVP，FR-1~19）** —— 来源 `_bmad-output/baseline/epics.md`：

| Epic | 主题 | FR |
|------|------|----|
| 1 | 项目基础设施与 LLM 通信 | FR-1~5, 19 |
| 2 | 自主 Agent 核心循环 | FR-6~9, 14 |
| 3 | 对话持久化与上下文管理 | FR-13, 15 |
| 4 | 自学习记忆系统 | FR-10~12 |
| 5 | 多 Agent 并行编排 | FR-16, 17 |

**Epic 6-10（自学习闭环扩展，FR-20~24）** —— 来源 `_bmad-output/baseline/epics-self-learning.md`，补齐从「被动工具」到「主动学习者」的能力：

| Epic | 主题 | FR |
|------|------|----|
| 6 | Context Files 自动加载 | FR-20 |
| 7 | SOUL.md 人格系统 | FR-21 |
| 8 | Memory Nudge 记忆提醒 | FR-22 |
| 9 | Skill Curator 技能策展 | FR-23 |
| 10 | Cron 定时调度 | FR-24 |

> MVP 范围内的 FR-18（MCP 工具发现）当时标注「延后」，后由 MCP 周期承接。

### 2.2 MCP Client 集成周期 · Epic 11-13

来源 `_bmad-output/mcp-client/`，独立 brief/prd/architecture/epics：

| Epic | 主题 |
|------|------|
| 11 | MCP 工具桥接（FR-1~8：配置加载、tool↔ToolSchema 映射、ClientManager 生命周期、CLI 装配） |
| 12 | GitHub 只读验收（FR-9：E2E 锁定真实工具名） |
| 13 | 安全边界与开源可用（FR-10/11：安全声明覆盖 MCP 不可信边界 + 开源文档） |

### 2.3 补丁周期 · 技术债收尾

`_bmad-output/patches/` 扁平存放计划外补丁，`deferred-work.md` 跟踪遗留项。已交付：`3-3-token-counter`、`5-1-subagent-context-injection`、`epic-5-context`、`p0-provider-hardening`、`fr3-mcp-auto-unregister`（FR-3 MCP 运行时断连 auto-unregister）。另有两份轻量回顾：`retrospective-engine-p5.md`、`retrospective-p0-tech-debt.md`。

### 2.4 engine/ 增量 · epic 外 P0-P5

运行时治理层（`PolicyEngine` + `ToolExecutor` + `store/ledger/observability`）按 P 批演进，不挂 Epic 编号，进度记入 `frame.md` 4.12：

| 批次 | 内容 |
|------|------|
| P0 | loop engine runtime 落地 |
| P1/P2 | 多 agent 角色化 + supervisor 编排 |
| P3/P4 | checkpoint-resume + 工具执行幂等 |
| P5-3/P5-4/P5-5 | 结构化子任务结果（`SubTaskOutcome`）+ `parent_run_id` 树形聚合 + resume 流式版 |
| P5-1/P5-2 | **deferred** —— 经评估暂不反转（D1/D4），依据记入 `frame.md` 4.12 |
| sandbox 后端 | `execute_in_sandbox` 接 `CommandRunner` 抽象（`tools/sandbox.py`）：默认 Passthrough，可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），经 `RuntimeSlot` 注入 |

### 2.5 迭代时间线（git log 提炼）

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

---

## 三、经验教训（轻量 retrospective）

> 下面是从 `deferred-work.md`、`frame.md` 已知缺口、git log 反推的跨 epic 教训。`sprint-status.yaml` 里 epic-1~12 的 `epic-N-retrospective` 均为 `optional`/未做；epic-13 retrospective 已完成（产物 `_bmad-output/mcp-client/retrospective-epic-13.md`）。若要为其余 epic 补做严格意义的 BMad 回顾，用 `bmad-retrospective` skill 单独生成。

1. **edge case hunter 会误判并发竞态**（Epic 5 / SubAgent）：deferred-work 第一条把「多协程访问共享 SkillStore」判为竞态，经核实不成立——`record_usage` 是无 `await` 的同步原子段，单线程 asyncio 下必然串行。**教训**：审查发现要核实是否真有 `await` 交错，加回归测试锁定不变量即可。
2. **异常包装要加守卫，避免双层重包**（Epic 1 / ProviderChain）：provider 源头包成 `ProviderError` 后，chain 的 `except` 又包一层。**教训**：`_wrap_error` 类入口加 `if isinstance(e, ProviderError): raise`；用 `__cause__` 链断言写回归测试。
3. **流式与同步路径要对称**（Epic 1）：`send()` 的 backstop 跟踪 `last_error`，`stream()` 版本一度漏了。**教训**：成对的 send/stream 实现要互相对照，补齐对称路径。
4. **安全边界必须诚实声明，不制造「更安全」假象**（Epic 13 / engine）：`SafetyGuard` 与 engine sandbox 都不是真边界。**教训**：安全相关代码注释里写明「非真正边界，须 OS 级沙箱兜底」，见 `CLAUDE.md` 文首声明。
5. **两种模式并存要标记冲突，而非折中**（engine / 工作区路径双重围栏，**已收敛**）：`PolicyEngine._validate_paths()` 与 `tools/path_safety.py` 曾两套围栏并存。**教训**：改其一须同步评估另一处，冲突在文档显式标出——后经收敛为共用 `resolve_under_root` 单一算法（两层有意纵深防御）解决（2026-07-01 commit `2ae99ed` 落地，`c7171ba` 同步 frame.md/CLAUDE.md 已知缺口）。
6. **评估结论要留依据**（engine P5-1/P5-2）：暂不反转的决策（D1/D4）把理由写进 `frame.md`，避免日后重做时忘记为何如此。
7. **缓存命中仍须复核策略裁决**（engine / ExecutionLedger）：ledger COMPLETED 缓存命中后曾直接返回，未复核最新 policy——若 policy 收紧为 `BLOCKED` 仍返回缓存会绕过门禁。**教训**：缓存层与策略层交叉时，命中后仍须过一遍 policy（commit `84ee783`）；同理 lease-active 命中跳过执行，防并发/重入重复跑 handler（`c07f811`）。

---

## 四、路线图与下一步

**当前缺口**（详见 `frame.md` 第五章）：

- `SafetyGuard` / `path_safety` / engine sandbox 均非真边界，须 OS 级沙箱兜底。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），file/memory 等不受覆盖。
- MCP V1 边界：`SafetyGuard` 未覆盖 MCP 工具（deferred DP-4）；仅接 Tools 原语。

**下一步候选方向**（按周期类型）：

- **epic 外增量**：engine P5-1/P5-2 若反转，需新开 P 批。（接真实 sandbox 后端已交付 2026-07-08：`CommandRunner` 抽象 + `FirejailBackend`，见 `tools/sandbox.py`。）
- **补丁周期**：MCP deferred 项（DP-4 安全覆盖）可开 spec。（FR-3 断连 auto-unregister 已交付，`tools/mcp/manager.py` `_watch`。）
- **集成周期**：MCP Resources/Prompts 原语、写操作（目前仅 Tools）。

**retrospective 补全**：如需为已完成 epic 补做正式回顾，对单个 epic 调 `bmad-retrospective` skill；本文第三章已提供轻量替代。

---

## 五、相关索引

- 架构权威：[`frame.md`](frame.md)（含 engine 模块 4.12、已知缺口第五章）
- 产品愿景：[`design.md`](design.md)
- 迭代原始产物：`_bmad-output/baseline/`、`_bmad-output/mcp-client/`、`_bmad-output/patches/`
- sprint 状态：`_bmad-output/baseline/sprint-status.yaml`
- 技术债登记：`_bmad-output/patches/deferred-work.md`
- 已产出 retrospective：`_bmad-output/patches/retrospective-{engine-p5,p0-tech-debt}.md`、`_bmad-output/mcp-client/retrospective-epic-13.md`
