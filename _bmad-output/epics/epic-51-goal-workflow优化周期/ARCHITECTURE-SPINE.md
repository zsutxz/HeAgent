# Epic 51 架构脊柱：`/goal` 与 workflow 可信交付优化

- 建立：2026-09-29
- 状态：冻结（freeze）
- 输入：`docs/goal-optimization-plan.md`、`docs/frame.md`、现有 `/goal` 代码与测试

## 0. 架构范式

**单一状态机 + 端口适配 + 证据驱动 Gate**。

```text
workflow.md / 受控 GoalScript
        ↓
Workflow loader / Script adapter
        ↓
WorkflowRunner（唯一状态机）
        ↓
CheckpointStore（唯一状态持久化）
        ↓
执行端口 → AgentLoop → PolicyEngine → ToolExecutor → SafetyGuard → handler
        ↓
EvidenceRecord → Quality Gate → 报告/控制面
```

## 1. 不变量

| ID | 规则 | 防止的分歧 |
|---|---|---|
| AD-1 | `WorkflowRunner` 是唯一状态机；workflow、CLI、GUI、cron、脚本都不得自行推进状态。 | 多套恢复语义和直接状态赋值 |
| AD-2 | `WorkflowCheckpointStore` 是唯一 checkpoint 写入口；第一阶段不改现有外部 JSON 形状。 | 双写与存量 Goal 失效 |
| AD-3 | 状态变化统一为 `transition(source, event)`；非法组合抛 `WorkflowTransitionError`。 | 条件分支漂移与静默修正 |
| AD-4 | 跨模块状态、证据、决策与脚本请求均使用 Pydantic 模型，不传原始 dict。 | 协议漂移与弱类型恢复 |
| AD-5 | 报告与证据分离。只有受治理执行路径生成的 Evidence 才能满足命令/Git/质量 Gate。 | Markdown 伪造“已测试” |
| AD-6 | 工具执行链保持 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。 | workflow 或脚本绕过治理 |
| AD-7 | CLI、GUI、cron 共用 `goal/application.py` 的确定性用例；入口层只适配输入输出。 | 三入口语义分叉 |
| AD-8 | workflow 在 Goal 创建时冻结标识与 revision/hash；恢复时资源漂移 fail-loud。 | 运行中静默换流程 |
| AD-9 | GoalScript 默认关闭，仅可信本地包可启用；它不是安全边界。 | 任意 Python 被误当沙箱 |
| AD-10 | 不能证明并行安全就串行；`max_parallel_stories` 不是安全证明。 | 写集冲突和顺序依赖 |
| AD-11 | 不自动 commit；Git 只作为变更与基线证据，提交需用户明确确认。 | 未授权版本操作 |
| AD-12 | OS 容器/VM/firejail 才是真正安全边界。 | 对内置治理的错误安全承诺 |

## 2. 模块落位

```text
src/heagent/engine/
  workflow_events.py       # 事件枚举
  workflow_transition.py   # 唯一转换表
  workflow_runner.py       # 唯一运行时
  workflow_resource.py     # 声明式资源模型

src/heagent/goal/
  doctor.py                # 只读预检
  status_view.py           # 统一状态投影
  evidence.py              # Evidence Pydantic 模型
  quality_gates.py         # 证据驱动 Gate
  decisions.py             # 审批/拒绝/修订记录
  script_api.py            # 受控 facade
  script_loader.py         # 包资源和入口校验
  script_runtime.py        # 脚本请求适配到 Runner
  application.py           # CLI-free 用例层
```

`engine/` 不得导入 `goal/` 或入口层；`goal/` 可依赖 `engine/`；`cli/goal.py` 只负责命令分发和渲染。

## 3. 状态与事件

- 外部状态保持：`PENDING`、`RUNNING`、`WAITING_USER`、`BLOCKED`、`FAILED`、`COMPLETED`。
- 事件至少包括：`START`、`STEP_COMPLETED`、`CHECKPOINT_REQUIRED`、`USER_RESUME`、`USER_PAUSE`、`INPUT_MISSING`、`GATE_FAILED`、`EXECUTOR_FAILED`、`FINAL_STEP_COMPLETED`、`CANCELLED`。
- 每个状态赋值必须能追溯到一个事件。
- 观测 sink 失败只记 warning，不改变状态机结果。

## 4. Evidence 与 Gate

`EvidenceRecord` 必须关联：`goal_id`、`story_id`、`workflow_id`、`workflow_revision`、Git base/head、变更文件、命令证据和质量门结果。

命令证据至少包含：工作目录、命令摘要、退出码、耗时、输出 digest/有界脱敏摘要、失败分类。

Gate 规则：

- 缺证据不能用报告文本补齐；
- 失败/超时/取消/策略阻断均有显式证据；
- 结构化 Gate 缺失时旧 workflow 保持文本 Gate 行为；
- 新字段非法时 fail-loud，不静默回退旧语义。

## 5. 审批与 workflow 冻结

- `approve`、`reject`、`amend`、`resume` 是不同事件。
- cron 不得自动批准人工 Gate。
- 决策记录追加式保存，重跑不得覆盖历史。
- workflow 标识、revision/hash 在创建时写入 Goal 元数据；老 Goal 缺字段时按兼容规则绑定 `he-goal`。

## 6. GoalScript 边界

允许：声明步骤、受控并行、checkpoint、读取已登记输入/产物、记录假设、请求决策、调用受控验证器。

禁止：直接写 checkpoint/workflow/current、直接文件写、`run_shell`、子进程、裸网络、Git commit、访问 AgentLoop/PolicyEngine 内部状态。

第一阶段在宿主解释器运行时只支持可信本地包，并强制资源完整性校验、步骤/深度/超时上限。第三方脚本必须等待隔离 worker；该 worker 不在本 Epic 的强制交付范围。

## 7. 安全并行

Story 元数据：`depends_on`、`parallel_group`、`write_set`。

并行前必须满足：依赖完成、写集不相交、不共享单写者产物、同一 Epic、独立 checkpoint/evidence、恢复后不扩大并行度。任一条件未知即串行。

## 8. 兼容性

- 继续支持 `brief.md`、`require.md`、`GOAL.md`。
- Phase 1 不迁移 checkpoint JSON。
- 新增 schema 时必须有版本、旧读、新写门槛、失败不覆盖原件与回滚说明。
- 旧 workflow 无新增字段时使用现有默认语义。

## 9. 验证纪律

- 每个 Story 必须有正向测试、负向验证和必要的变异体。
- 改 `engine/` 或包依赖时同步 `tests/test_architecture_contracts.py`。
- 验证数字只能来自亲跑命令。
- 最终质量门：相关 pytest、全量 pytest、ruff lint/format、`mypy src` 与 `mypy src --platform linux`。
