# 目标驱动开发周期 · Retrospective（Epic 41）

> 日期：2026-09-18（**补做**：原 `_bmad-output/sprint-status.yaml:409` 标记 `epic-41-retrospective: optional`）
> 范围：`_bmad-output/epics/epic-41-目标驱动开发周期/`（Epic 41，4 个 story：41.1 ~ 41.4；目录内**无** `stories/`，story 契约由 `epics.md` + `spec-41-1`/`spec-41-2` + `spec-goal-command/` 承载，见 `consolidated-overview.md:786`）
> 动机：给交互 CLI 补 BMad 式目标驱动入口——`/goal <描述>` 一条命令启动 skill、逐 story 独立会话推进、进度落盘可续跑（`epics.md` Epic 41 段）

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 41.1（FR-1）· commit `81264bb` | `/goal new/next/status/reset`：skill 正文路径直读注入、每步全新 SubAgent 会话、GOAL.md 边界扫描（`src/heagent/cli.py` +301 行，`tests/test_goal_command.py` +639 行） |
| 41.2 + 41.3（FR-2/3/4）· commit `08a4294` | `/goal run` 循环、`SubAgent(metadata=...)` 透传 `goal_id`/`goal_kind`（`agent/sub.py` +16 行）、`/goal auto` cron 前缀路由（`cli_goal.py:69` `_GOAL_AUTO_PREFIX = "goal-advance "`）、TUI `/goal` 路由（`gui/screens/chat.py` +26 行）、`docs/frame.md` +21 行 |
| 评审修正 · commit `2f53406` | 工作流评审发现项硬化（`cli.py` +45 行、`tests/test_goal_command.py` +43 行） |
| 41.4 收尾 · commit `90a8dc4` | goal 契约归档（`spec-goal-command/SPEC.md`、`goal-workflow-contract.md`）并关闭评审（10 files，+244/−10） |
| 机制层拆分 · commit `02f084e` | 命令族拆为独立模块 `src/heagent/cli_goal.py`（+1103 行），`cli.py` −1068 行 |
| 遗留项闭合 `855d135` / `d7dc758` / `44ab001` | 跨进程锁（E41-D5，2026-09-17）、Step 07 `max_iterations: 100`（E41-D6，`.heagent/workflows/workflow.md:192`）、GUI `/goal` 收口（E41-D7，4 files +305/−7） |

## 二、做对的

1. **分层铁律真正落地**——方法论 = skill / 工作流文本，机制 = CLI 薄代码；`spec-41-1` 的 Never 段明令不建 `goal.py`、不引入 Pydantic `GoalState` 与 `runs.jsonl`，后续工作流演进确实只改文本（`d7dc758` 仅改 `workflow.md` 2 行）。
2. **会话边界 = story 边界**——每步全新 SubAgent 会话 + `WindowResetConfig(threshold=get_settings().window_reset_threshold)`（`cli_goal.py:925`；阈值默认 0.6 见 `config.py:145`），长目标靠清窗续跑而不是撑爆上下文。
3. **四种失败面全部显性化**——skill 缺失、GOAL.md 无合法 status 行、触顶（默认 10 轮）、白跑（checkbox 计数零变化）都回显报错，不静默续推（`spec-41-1`/`spec-41-2` 的 I/O 与边界矩阵）。
4. **观测透传不污染框架键**——`SubAgent` 先合 role metadata、再合 caller（caller 胜），`kind=subagent` 保留；E41-D4 明确裁定**不做**默认并入 `RunContext.metadata`（policy / window-reset 键归框架所有）。

## 三、可改进的

1. **并发正确性交付时缺位**——41.1/41.2 只有进程内 `asyncio.Lock`，同 workspace 双进程同时推进会互相覆盖 `GOAL.md` / `current` 指针，到 E41-D5（`855d135`）才补 `persist.file_lock`（`persist.py:394`）+ `_goal_mutex`（`cli_goal.py:89`，接入 7 个变更入口）。
2. **机制增量远超规划预算**——`epics.md` NFR-1 写明「机制代码全落 `cli.py`，增量约 130 行内」，而四次提交对 `cli.py` 的新增分别为 +301（`81264bb`）/ +204（`08a4294`）/ +45（`2f53406`）/ +45（`90a8dc4`），随后 `02f084e` 不得不拆出 1103 行新模块；§17.4-A3「`cli.py`/`cli_goal.py` 职责再拆」至今仍开（已另落地 `cli_init.py`、`goal/document.py` 两批）。
3. **测试资产中途改名留下断链**——`tests/test_goal_command.py`（`81264bb` 新建、`90a8dc4` 仍在扩写）已在 `e9a4619` 删除（`git log --diff-filter=D` 唯一命中），职责并入 `tests/test_goal_declarative_workflow.py`；而 epic-42 的 `stories/42-5-compatibility-regression.md` 验证记录里引用的是这个已不存在的文件。
4. **story 级文档缺位**——本周期没有 `stories/` 目录，41.2/41.3 的验收只存在于 `spec-41-2` 与 `epics.md` 中，事后按 story 追溯比 Epic 40/42 两周期费力。

## 四、教训

1. **「文本驱动」的前提是机制预算足够薄**——分层设计本身成立（改工作流零代码），但首版机制一旦被自己的体量逼着拆模块，就说明「增量预算」应当写成验收项而不是规划口号。
2. **边界判定交给 LLM 写盘，必须给每种失败配显性报错**——没落盘 / 白跑 / 触顶若不报错，失败会长得像成功（与 `consolidated-overview.md` §12.3 教训一致）。
3. **并发正确性不能归入「后续优化」**——同一 workspace 双进程写同一状态文件属数据丢失类缺陷，应在交付 story 内就用跨进程锁兜住，而不是等优化批次。
4. **测试文件的改名/合并要留指针**——被删的 `tests/test_goal_command.py` 至今仍被其他 epic 的 story 文档引用，说明「测试资产也是对外证据」。

## 五、遗留项状态

- 已闭合：E41-D1 ~ E41-D7 全部（`deferred-work.md` 状态总览）。逐条证据：D1 = `cli_goal.py:924` + `tests/test_goal_declarative_workflow.py:709`；D2 = `gui/screens/chat.py` + `tests/test_gui_goal.py`；D3 = `tests/test_cli.py:128`；D4 = `agent/sub.py` + `tests/test_sub_agent.py:66`；D5 = `855d135`；D6 = `d7dc758`；D7 = `44ab001`。
- 仍开：本周期在活动台账暂无未闭合项（`deferred-work.md` 首段自述）。
- 跨周期活动项：`cli.py` / `cli_goal.py` 职责再拆（低，§17.4-A3）——指向 `_bmad-output/implementation-artifacts/deferred-work-archive.md`。
- 立场提醒：E41-D5 的锁是**并发互斥**，不是 OS 级安全边界（`deferred-work.md` 立场段）。

## 六、结论

Epic 41 用「skill 承载方法论、CLI 只做机制」换来了零代码的工作流演进能力，这是本周期最有价值的沉淀；显性失败矩阵与 run metadata 观测也都按契约落到了代码与测试。代价是机制层的实际体量与规划预算差了一个量级，并留下并发锁、职责拆分、story 文档缺位三笔延后账——后续同类 epic 应把「增量预算」与「跨进程正确性」直接写成验收条件。
