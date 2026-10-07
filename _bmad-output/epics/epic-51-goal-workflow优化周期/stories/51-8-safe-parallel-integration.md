---
id: 51-8
title: Story 依赖图、安全调度、集成验收与文档收口
status: done
parent_epic: E51
priority: P1
depends_on: [51-3, 51-4, 51-5, 51-6, 51-7]
blocks: []
created: '2026-09-29'
---

# Story 51-8：Story 依赖图、安全调度、集成验收与文档收口

## 用户故事

作为 Goal 负责人，我希望并行只在依赖和写集可证明安全时发生，并用完整回归证明新能力不破坏旧 Goal。

## 声明面（主要交付物）

- story 文档（`02-epics.md` 的 `### S-N` 段内）新增字段：**`depends_on`**、**`parallel_group`**、**`write_set`**。
  - 未声明 `write_set` = 写集未知 = **串行**（不猜、不推断）。这是 AD-10 的声明形态。
- `max_parallel_stories` 只表达**上限**，永远不是安全证明。
- 当前宿主回调没有可验证的写入隔离，因此 `parallel_group` / `write_set` 仅作声明元数据；
  执行器固定每次运行一条 Story，并在下一条开始前持久化 checkpoint / evidence。
- **验收演示（第 0 节口径）**：改动 Story 的依赖 / 写集（**只改文档**）即可改变解析出的声明，
  `src/` 零改动；声明本身不得提升并行度。

## 引擎面（最小通用能力）

- Story 解析模型补三个字段（缺省为空 → 串行），由既有 `parse_story_list` 扩展，不另造解析器。
- 通用执行规则：依赖必须已完成；任一未知或未完成依赖即 `BLOCKED`。即使写集声明不相交，
  没有隔离执行器也保持串行。
- 每条 Story 的 started / completed / failed 事件、checkpoint 与 evidence 仍独立记录。
- **为什么声明层表达不了**：依赖是否已经完成属于 Runner 持久态，必须由通用状态机判定；
  `parallel_group` / `write_set` 不能证明回调实际写入隔离，故不能授权并发。

## 验收标准

- Story 支持 `depends_on`、`parallel_group`、`write_set`。
- 依赖未完成或未知时不运行；其余形态（包括写集不相交）固定一次一条 Story。
- 每条 Story 各有 checkpoint、证据与 started / completed / failed 事件；恢复不重复已完成 Story。
- 存量 `brief.md`、`require.md`、`GOAL.md`、旧 checkpoint 和旧 workflow 可恢复。
- 样例 Goal 完成 doctor、审批、证据 Gate、workflow 冻结、脚本步骤和 fail-closed Story 调度。
- CLI、GUI、cron 对同一状态和决策结果一致。
- `docs/frame.md`、`docs/goal-workflow.md`、工作流资源和架构契约同步。
- **只改 story 文档即可改变依赖闸门的结果**（以实测增量作为证据）；写集声明不得提升并行度。

## 任务

- [x] 扩展 Story 解析模型（`depends_on` / `parallel_group` / `write_set`；缺省为空）。
- [x] 实现依赖闸门与逐 Story 事件 / checkpoint；写集不作为并行授权。
- [x] 新增集成样例与旧资产恢复矩阵（2026-10-07，`tests/test_story_scheduling_integration.py`：
  引擎级全链样例——依赖闸门零执行 BLOCKED → 串行逐 story checkpoint/状态 → 审批门 → approve
  放行合并输出 → 恢复不重跑；恢复矩阵参数化三种历史 checkpoint 形态（as-is / 含已移除
  `story_batches` 字段 / 缺 `active_stories`+`story_statuses` 的极简旧形）全部可恢复续跑。
  CLI 级宿主环节各有专属判据文件，见该文件 docstring 的分工声明）。
- [x] 收口台账中的验证重跑观测、异常路径持久化与重复执行问题（2026-10-07，见下方「台账收口记录」）。
- [x] 运行对抗式代码评审、全量质量门并完成 retrospective（2026-10-07，见下方「对抗式评审记录」）。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py tests/test_story_loop.py -q
pytest tests/test_architecture_contracts.py -q
pytest
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```

## 实测证据（2026-10-07，本机亲跑，收口批 + 集成样例 + 评审修复后复跑）

```text
pytest -q（全量）            → 3603 passed, 14 skipped, 18 deselected
ruff check src tests         → All checks passed!
ruff format --check src tests → 313 files already formatted
mypy src / --platform linux  → 164 files，均 no issues
```

## 收口纪律

- 不自动 commit。
- 未亲跑的命令不得写成通过。
- 全量验证若受本机环境影响，必须做基线对照并如实记录。

## 台账收口记录（2026-10-07）

三项台账遗留一次收口（TDD：8 个新测试先 RED 后 GREEN）：

- **异常路径持久化**（51-2 评审递延「转换后不持久化，重启 restore 复活 RUNNING」）：
  `WorkflowRunner.run_step` 的异常分支在 `_absorb_step_exception` 转换后经新方法
  `_persist_interrupted` 落盘（best-effort：`asyncio.shield` + 异常只记日志不替换原异常；
  取消场景落盘在后台尝试完成）。判据 `test_story_failure_persists_failed_checkpoint`。
- **验证重跑观测**（51-4 递延「emit/ledger 接线」）：
  ① 新事件 `workflow_gate_evaluated`（`cli/goal.py:_emit_goal_gate_event`）——完成门
  （`source=completion_gate`）与 `/goal verify`（`source=verify_run`）每次结构化求值各发
  一条（verdict / failed / rerun_evidence / reused_commands / duration_ms），emit 异常隔离；
  ② 每次受治理重跑在 `ExecutionLedger` 留 `scope="goal-verify"` 审计记录（outcome /
  duration 进 metadata；键含唯一 call id，**只审计不去重**——ledger 的 already-completed
  短路是永久态，不能做 verify 去重）；台账故障只记日志，绝不阻断治理执行。
- **重复执行**（51-4 递延「声明验证命令随完成门与 verify run 各执行一次」）：
  `verify_step` 新增 `rerun_policy`（`Literal["always", "if_stale"]`，缺省 always）。完成门
  保持 **always**——证据必须反映当前这次步骤执行（AD-5；BLOCKED 重跑后步骤内容可能已变，
  旧证据不可信）。`/goal verify run` 改 **if_stale**——仅重跑「缺证据 / 失败 / 过期 / 绑定
  漂移」的命令，新鲜成功证据**复用不重跑**，复用清单显性进
  `VerificationReport.reused_commands` 并渲染（`reused fresh evidence, not re-run`）。
  判据：3 个单测（复用 / 失败重跑 / 过期重跑）+ 1 个语义锁定测试（always 不复用）+
  CLI 集成（`test_goal_verify_run_reuses_fresh_command_evidence`）。

受治理端口测试的 ledger 全部重定向 tmp（裸 `EngineContainer()` 不再向真实 `.heagent/ledger`
写审计记录）。`docs/frame.md` 4.16 事件契约表同步（`workflow_step_*` 行去掉批次描述、新增
`workflow_gate_evaluated` 行）。

## 对抗式评审记录（2026-10-07，独立评审代理）

**结论：无 CRITICAL/HIGH；2 MEDIUM + 3 LOW 全处置**（REQUEST CHANGES → 修复后可合入）：

- **[MEDIUM] 审计记录丢 command**：`ledger.complete` 整体替换 metadata，acquire 写入的
  `command` 被覆盖 → COMPLETED 审计无法回答「哪条声明命令被执行过」。修复：command 并入
  complete 的 metadata；测试补 `metadata["command"]` 断言。
- **[MEDIUM] acquire 与 try 之间悬挂 RUNNING 窗口**：`evaluate_tool_call` / `get_schema` /
  `resolve_runtime_config` 抛错会让台账记录悬挂到租约超时。修复：acquire 挪到
  `executor.execute` 紧前，执行本体全部罩进配对 try。
- **[LOW] 取消路径 story_statuses 硬编码**：改用事件词汇（`WorkflowEvent.CANCELLED.value`）
  与失败（`WorkflowStatus.FAILED.value`）如实区分——取消的 story 不谎报 failed。
- **[LOW] emit details 构造在隔离 try 之外**：移入 try，`step`/`story` 属性访问故障与
  总线故障同归隔离。
- **[LOW→接受] shield 后台任务孤儿语义**：进程关停期落盘可能未完成（复活风险残余），
  docstring 已声明 best-effort，接受并留档。
- 评审正面确认：if_stale 预求值的漂移/歧义/gate 子句交互无缺陷；AD-5 完成门无条件重跑
  保持；ledger 无幂等去重；`_persist_interrupted` 异常不被替换、取消落 PENDING 合理。

## Retrospective（Story 51-8）

- **做对了**：批次机制拆除一次到位（-474 行净删），串行语义成为唯一路径后 M-1 的
  `story_statuses` 死状态、emit/ledger 缺位等观测债由审查系统性暴露并一次清偿；声明面
  （plan §11 / story 改题）与代码同步修订，未留「文档说并行、代码只串行」的裂缝。
- **可改进**：① 51-4 交付时把「重复执行」「观测接线」递延给 51-8，但递延条目未写明
  修复方向（去重判据 / 语义归属），本 story 花了调研成本重建设计上下文——递延应带
  「建议修法」；② 集成样例落在引擎级（CLI 级宿主环节依赖既有分散判据），「一个样例
  Goal 走完 CLI 全链」仍是缺口，记入下方遗留。
- **遗留（如实记录）**：CLI 级全链样例（doctor → new 冻结 → 审批 → 证据 Gate → 脚本
  步骤 → fail-closed story）未建成——各环节判据已独立存在，组合判据留待后续按需补。
