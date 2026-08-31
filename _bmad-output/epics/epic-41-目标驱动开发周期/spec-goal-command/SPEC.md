---
id: SPEC-goal-command
companions: [goal-workflow-contract.md]
sources: [C:\Users\skype\.claude\plans\swirling-bubbling-ocean.md]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# HeAgent /goal 命令 —— 目标驱动开发

## Why

把 BMAD 式「目标 → 拆 story → 逐 story 独立会话推进」的开发流带进 HeAgent 产品本身。机制底座已全部现成（SlashRegistry 注册表 / SubAgent 每次 run 全新 AgentLoop / WindowReset token 阈值清窗续跑 / cron JobStore 持久调度），缺的只是一个把「方法论 = skill 文件、机制 = 薄代码」这一分层落成产品能力的入口命令。用户（tan）在可行性探讨与两轮澄清中反复锚定：HeAgent 只做机制（探测 LLM 流量阈值与 story 完成边界，触发清窗、落盘、新会话、下一任务），工作流方法论必须由人可直接编辑的 skill 文件承载，goal 不得写成 Python 状态机模块。

## Capabilities

- **CAP-1**
  - **intent:** 用户可以在交互 CLI 里以 `/goal <描述>`（或 `/goal new <描述>`）新建 goal 并触发一次 planning 会话，产出含 story 清单的 GOAL.md 状态文件。
  - **success:** 脚本化测试：goal 目录、current 指针、goal.txt、GOAL.md（status=executing、≥1 条 story）全部就位，回显 planning 摘要。
- **CAP-2**
  - **intent:** 用户可以以 `/goal next` 推进一条 story，每步是一个全新隔离子会话（fresh context + 新 LLM 连接），会话边界即 story 边界。
  - **success:** 脚本化测试：prompt 含 skill 正文与状态文件内容；run 后 story 勾选被扫描到；`.heagent/runs/` 每 story 独立 run 记录。
- **CAP-3**
  - **intent:** 用户可以查看进度（`/goal status`，裸 `/goal` 同义）与停用当前 goal（`/goal reset` 清指针、保留文件）。
  - **success:** 测试：status 打印进度计数与 GOAL.md 全文；reset 后 current 清空、目录保留。
- **CAP-4**
  - **intent:** 用户可以以 `/goal run` 连续推进 story 直至 done，无需逐条手动触发。
  - **success:** 测试：跨轮脚本化推进至 done；触 max rounds（默认 10）显性报错不静默。
- **CAP-5**
  - **intent:** 用户可以以 `/goal auto <cron 表达式>` 注册定时推进（默认 `*/15 * * * *`），CLI 重启后续跑，goal 完成或 blocked 后 job 自动注销。
  - **success:** 测试：前缀路由命中 goal 路径（非前缀走原路径）；done/blocked 后 JobStore 中 job 消失；并发锁语义（推进期间第二次调用等待）。
- **CAP-6**
  - **intent:** 系统只以两个机器可读标记判定 goal 边界（GOAL.md 的 status 行 + checkbox 完成度），skill 缺失、状态文件缺失/违约、无活跃 goal 均显性报错。
  - **success:** 纯函数直测：全勾/`status: done`→done；blocked→停；缺 status 行→报错；会话返回但状态文件未写→显性报错。
- **CAP-7**
  - **intent:** goal 会话的运行记录可在 engine 观测体系（RunStore 快照）中按 goal 过滤。
  - **success:** 测试：SubAgent 传 metadata={goal_id, goal_kind} 后子 run 快照 metadata 含这些键且 kind=subagent 保留；默认 None 行为不变。

## Constraints

- 方法论（工作流规程、GOAL.md 状态契约）只存在于 `.heagent/skills/goal/SKILL.md`，人可直接编辑定制；禁止 `goal.py` 独立模块、Pydantic GoalState、迁移校验表、runs.jsonl 审计文件。
- 机制代码全部落 `cli.py`（`_goal` handler + 模块级私有 helper），增量约 130 行内，仿 `_dream_runner` / `_run_job` 闭包先例。
- 每个 goal 会话 = 全新 AgentLoop/RunContext（复用 SubAgent），token 阈值经 `WindowResetConfig(threshold=settings.window_reset_threshold)` 清窗续跑。
- skill 注入为确定性路径直读 `.heagent/skills/goal/SKILL.md`，不走 SkillStore 相似度匹配。
- 无人值守不提升任何权限：照走 PolicyEngine，审批按既有 fail-safe 语义（拒绝 → story blocked → 注销并回显）。
- `sub.py` metadata 参数向后兼容，默认 None 不改变现有行为。
- 测试遵守仓库惯例：内联 StubProvider 脚本化 tool_calls、`monkeypatch.chdir(tmp_path)` 隔离真实 `.heagent`、每测试 `reset_settings()`。
- 子命令参数缺失打印用法，不做交互式追问（REPL 内不 `input()`）。
- goal 会话期间 REPL 阻塞接受 Ctrl+C 打断，兜底回显「状态在盘，`/goal next` 可续跑」。
- `docs/frame.md`（架构权威）随实现同步增补 `/goal` 命令、skill 契约与 `.heagent/goals/` 目录说明。

## Non-goals

- 不做独立 review run（验收内嵌 story 规程）。
- 不做代码级状态机校验（Pydantic GoalState/迁移合法性表）——story 纪律靠 skill 契约 + 人工检查，有意取舍。
- 不做 goal 会话流式输出与 REPL 内打断（`SubAgent.run_stream` defer）。
- 不做 `goal_update` 类型化工具（file 约定 + 读边界扫描已定案）。
- 不做 `file_write` 原子化与跨进程锁（已知缺口，与现状 file 工具一致）。
- 不做 `SubAgentResult` usage 字段（token 观测 defer）。

## Success signal

`python -m heagent` 交互模式跑一个 2-story 小 goal：`/goal <描述>` 产出 planning，`/goal run` 逐 story 勾选推进且 `.heagent/runs/` 留下每 story 独立 run 记录，`/goal auto */1 * * * *` 定时推进且完成后 job 自动消失；全量 pytest / ruff / mypy 绿。

## Assumptions

- engine 经 `loop.engine` 公开属性获取，不扩 `_build_slash_registry` 签名。
- goal 目录 `.heagent/goals/<uuid4().hex[:8]>/`；`current` 指针文件存 goal_id；`goal.txt` 存原始描述（GOAL.md 缺失时重跑 planning 的恢复路径）。
- `/goal run` 的 max rounds 用常量默认 10，不进 Settings。
- cron 路由用 prompt 前缀 `goal-advance <goal_id>` 约定（CronJob 无结构化 metadata 字段），`_run_job` 闭包内前缀识别分流。
