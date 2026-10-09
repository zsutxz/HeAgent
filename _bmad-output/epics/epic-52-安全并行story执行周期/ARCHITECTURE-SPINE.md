# Epic 52 架构脊柱：goal 工作流安全并行 Story 执行器

- 建立：2026-10-09
- 状态：冻结（freeze）
- 输入：Epic 51 ARCHITECTURE-SPINE（AD-1..15 全部继承）、`docs/goal-workflow.md`、`docs/frame.md`、
  Story 51-8 规格与被删批次机制（commit ddf39bd）的教训清单

## 0. 架构范式

**声明门控授权 + 治理链围栏（预防）+ Git 审计（检测）+ 批次重推导（无常驻状态）。**

```text
story 文档三字段（parallel_group / write_set / depends_on）   ← 声明面（51-8 已交付，不新增词汇）
        ↓
WorkflowRunner.run_step
        ├─ 批派生 _parallel_batch（七条件纯推导，每次推进重算）
        ├─ 单 story / 不合规 → 既有串行路径（逐字节不变）
        └─ 合规批 → StoryExecutionContext(step, story, ctx) 第三参
                ↓
        gather(return_exceptions=True) 并发回调（批内单失败不连坐）
                ↓
        SubAgent(write_allowlist=…) → AgentLoop → PolicyEngine（write allowlist 预检）
                → ToolExecutor → SafetyGuard → handler      ← 围栏走既有治理链，零旁路
                ↓
        宿主审计（per-story 前后增量 ⊆ 声明写集 ∪ 兄弟写集）
                ↓
        按声明序逐成员记账 + 逐成员 _persist（RUNNING 快照）→ 单次终态转换
```

继承 Epic 51 第 0 节全部口径：声明即行为、`src/` 通用引擎、AD-13/14 准入证明。

## 1. 新增架构决策（AD-16..20，续 Epic 51 编号）

| ID | 规则 | 防止的分歧 |
|---|---|---|
| AD-16 | **批次是推导不是状态**：批成员每次推进由声明（`parallel_group`/`write_set`/`depends_on`/`max_parallel_stories`）与持久态（completed_stories、撤销闩）确定性重推导；不持久化批次、不新增 active_stories 类镜像字段；checkpoint 唯一新增字段是单向撤销闩（追加带默认值可选字段，AD-2 合规）。 | 47-9 式批次状态六写点同步税复活（A25/A26） |
| AD-17 | **声明门控的原地写集围栏**：授权并行的充要条件是七项全满足（见 §2）；被授权 Story 的 `file_write`/`file_edit` 受 per-run write allowlist 预检，走 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard → handler` 链内，零旁路（AD-6）；allowlist 缺失/为空 = 现状放行。围栏是纵深防御**非安全边界**（shell 可绕过，AD-12 同源）。 | 配置值直接变并发度；为围栏新造第二套工具通道 |
| AD-18 | **完成后审计与撤销闩**：并行 Story 完成后由宿主以只读 Git 端口做写集审计——per-story 会话前后增量基线（**非 HEAD**，AD-11 不自动 commit ⇒ 前序写入留在工作树）；tracked-modified 越集（排除兄弟写集与宿主自写产物）→ 该 Story FAILED + `write_violation` → Goal 级并行授权**单向撤销**；untracked 增量只记警告事件不判负（声明自身产生的验证夹具与产物就是未跟踪写入，严格模式必然假失败）。闩撤销的是并发授权，不撤销围栏——串行重跑仍带 allowlist、审计继续。 | 违规并行静默续跑；审计噪音摧毁可信度；重启后撤销失效 |
| AD-19 | **批是单 checkpoint 单元**：一次 `run_step` 内的批只做一次 START 与一次终态转换（转换表 RUNNING 终态全部单向，`workflow_transition.py`）；成员按声明序逐个记账并持久化 RUNNING 中间快照；批内单 Story 异常不取消同批（gather + return_exceptions），步骤级取消取消整批落 PENDING；`story_outputs` 按声明序合并（非完成序）。manual 模式下 checkpoint 确认从每 Story 一次收紧为每批一次（批已并发跑完，逐条确认无意义）。 | 逐成员终态转换打破转换表；完成序污染产物合并序 |
| AD-20 | **worktree 是后续增强层**：物理隔离（git worktree / OS 沙箱）改变的是围栏与审计的**实现强度**，不改变写集契约、七条件授权与审计语义；本 Epic 只固化契约，不实现隔离执行器。 | 为隔离重构已定的语义面 |

## 2. 批次授权七条件（定稿）

全部满足才形成 ≥2 的批（从 `story_index` 起按声明序，跳过已完成成员，遇首个不合规未完成 Story 即止）：

1. `step.max_parallel_stories > 1`；
2. 未命中 `story_parallel_revoked` 撤销闩；
3. 回调接受第三参 `StoryExecutionContext`（宿主实现围栏+审计契约的机器可测前置；两参老回调 = fail-closed 串行）；
4. 成员 `parallel_group` 相同且非空；
5. 成员 `write_set` 非空且批内两两不相交；
6. 成员 `depends_on ⊆ completed_stories`（**不允许**依赖批内成员——依赖并发中的 Story 不可证安全）；
7. 批大小 ≤ `max_parallel_stories`。

任一不满足 → 派生结果为 1，逐字节走既有串行路径（既有测试零改动）。

## 3. 声明层：词汇表增量

| 词汇 | 载体 | 现状 | 归属 Story |
|---|---|---|---|
| `depends_on` / `parallel_group` / `write_set` | story 文档 | Epic 51 已加（当时仅依赖闸门） | 本 Epic 起真正授权并发 |
| `max_parallel_stories` | 步骤 frontmatter | 已存在（死字段 + 警告） | 本 Epic 起成为门控上限 |
| `workflow_story_batch_scheduled` / `workflow_write_audit` 事件 | 引擎事件词汇 | 新增 | 52-2 / 52-3 |

不新增平行的顶层配置；story 文档三字段语义在 51-8 基础上**升级**（从"仅元数据"到"围栏输入 + 授权依据"），
声明格式零变更——存量声明自动获得新语义，但无宿主第三参契约时仍串行（条件 3）。

## 4. 执行上下文协议（引擎 ↔ 宿主）

```python
# pub/types.py（跨模块 Pydantic 模型，与 StorySpec 同居 pub）
class StoryExecutionContext(BaseModel):
    story_id: str
    parallel: bool                            # 本 Story 是否在授权并行批内
    write_allowlist: list[str]                # = 本 Story 声明 write_set（围栏输入）
    batch_members: list[str]                  # 批成员 id（含自己）
    sibling_write_sets: dict[str, list[str]]  # 兄弟成员 id → write_set（审计排除用）
```

回调签名探测（仿 `_accepts_story` 的 `inspect.signature` 先例）：回调接受 ≥3 位置参数才算实现契约。
`StepExecutor` / `goal/application.py` 桥透传该参数（缺省 None = 现状）。零 Epic 专用词汇（AD-13/14 合规）。

## 5. 审计语义（宿主侧）

- 基线：SubAgent 会话**开始前**采 `ReadOnlyGitPort.evidence()` 的 changed/untracked 集为 before，
  会话 + 质量门结束后再采 after，`Δ = after \ before`（per-story 增量，批内各 Story 各自持基线）。
- 判负式：`(Δ.changed \ ∪兄弟write_set \ 宿主自写产物路径) 非空 → FAILED + write_violation`。
- untracked 增量：发 `workflow_write_audit` 警告事件，不判负。
- 非 Git 项目：跳过 Git 审计（工具链围栏仍生效），发跳过说明事件。
- 并行 Story 的质量门命令重跑（AD-5 always）由宿主模块级锁串行化——LLM 会话并行，声明命令串行。

## 6. 恢复与失败语义

- 失败 Story 不进 `completed_stories`；`story_index` 停在首个未完成（允许 completed 有洞，批派生跳过
  已完成成员而非截断）；重跑与串行 resume 重试同构，部分写入残留由 Story 自身幂等性承担（既有语义）。
- 审计失败的 Story：归属即"执行失败"（宿主回调内判负返回 FAILED + write_violation），不进 completed。
  污染批的过度归因（无辜者连坐）是 fail-closed 的有意代价，reason 列出越集路径供甄别。
- 批内中断：外层取消 → gather 整体取消，未落账成员记 `cancelled`，步骤 CANCELLED→PENDING +
  `_persist_interrupted`，恢复从首个未完成 Story 起——与串行同构。
- 整个批在 `advance` 持有的 goal_mutex 内单次 `run_step` 中执行；批成员回调链（SubAgent 会话、
  质量门、审计）**绝不进入 goal_mutex**（跨 task 不享重入，且会自锁死）。

## 7. 引擎面落位

```text
src/heagent/
  pub/types.py                     # +StoryExecutionContext
  engine/policy.py                 # _validate_paths 增 write allowlist 检查（_WRITE_ALLOW_TOOLS）
  engine/workflow_runner.py        # 批派生纯函数 + 并行执行路径 + 闩 + 事件 + _accepts_execution
  engine/checkpoint.py             # +story_parallel_revoked（追加可选字段）
  agent/sub.py                     # +write_allowlist 参数（RunContext metadata 注入，reserved 防伪造）
  goal/application.py              # StepExecutor 协议透传 execution
  goal/workflow_loader.py          # _parallel_limit 警告 → 条件说明 INFO
  cli/goal.py                      # execution 接线 + _audit_story_writes + 质量门锁 + 判负返回
```

`engine/` 不得导入 `goal/`（审计用 `ReadOnlyGitPort` 落在 cli/goal 宿主侧，合法）；
`StoryExecutionContext` 归 pub（跨模块 Pydantic，AD-4）。

## 8. 验证纪律

- 语义翻转锚点：`tests/test_story_batch_safety.py:56`（峰值并发 1→2）、`:107`（重写为七条件反例矩阵）、
  `tests/test_workflow_resources.py:76`（WARNING→INFO）。
- 新增：调度矩阵（`test_story_parallel_scheduling.py`）、围栏（`test_write_allowlist.py`）、
  审计（`test_story_write_audit.py`）；`test_story_scheduling_integration.py` 扩展并行形态与恢复矩阵
  （+revoked、+批中间 RUNNING 快照）。
- AD-13/14 验收：只改 story 文档声明（加/去 `parallel_group`）翻转批派生结果，`src/` 零改动。
- 改 `engine/` 包依赖时同步 `tests/test_architecture_contracts.py`。
- 最终质量门：全量 pytest、ruff lint / format、`mypy src` 双平台，亲跑留痕。
