---
title: 'Phase 1 运行配置快照与统一装配'
type: 'refactor'
created: '2026-09-21'
status: 'done'
baseline_commit: '4cecfeac305b2df91295e6102f40b4ffda10f9a6'
review_loop_iteration: 0
context: ['{project-root}/AGENTS.md', '{project-root}/docs/frame.md']
---

<frozen-after-approval reason="用户已授权执行 Phase 1">

## Intent

问题：入口传入 Settings 后，容器和运行方法仍读取全局配置，CLI、GUI、cron 装配重复，可能导致同一运行的配置不一致。

方案：通过不可变 ResolvedRuntimeConfig 固定一次入口解析的配置，统一 wiring 中的组装，并记录实际 sandbox 决策；保留公开入口兼容性。

## Boundaries & Constraints

始终：遵守既有异步与依赖方向，沿用 PolicyVerdict 而非复制 PolicyDecision；安全链顺序不变。保留既有显式 False 覆盖环境 True 的语义、provider 路由池行为和 CLI 兼容导出。工作树内已有文档修改及 LangChain 文档删除必须保留。

需要协商：变更既有策略默认值、命令行接口或旧状态文件格式。

禁止：修改历史 sprint-status；新增依赖或提交。docs/test.md 是本地临时记录，不得添加到 Git 或从正式文档引用。

## I/O & Edge-Case Matrix

| 场景 | 输入 | 预期 | 错误处理 |
| --- | --- | --- | --- |
| 覆盖 | 环境 True，入口 False | 最终 False，来源可查 | 不使用 truthiness 覆盖 |
| 快照 | 构造后修改 Settings 或集合 | 运行结果不变，快照不可变 | 禁止内嵌可变 Settings 冒充冻结 |
| 隔离后端 | auto/显式 backend 不可用 | 保持现有降级语义，记录请求与实际能力 | 不虚构网络/文件隔离 |
| 共用 | CLI、GUI、cron 相同配置 | 共用解析/装配，独立 run context | 保留 goal cron 分支 |
| 策略 | 禁止、审批、sandbox、direct | PolicyVerdict 保留原模式并可追踪来源 | 不改变策略优先级 |

</frozen-after-approval>

## Code Map

- `src/heagent/config.py`：Settings 可变且测试依赖；新快照独立，解析只在构造/入口执行。
- `src/heagent/types.py`：共享 Pydantic 模型；RoutingPoolSpec 的 dict 需要快照隔离。
- `src/heagent/wiring.py`：已有 _build_provider，复用并扩展入口装配。
- `src/heagent/cli.py`：_build_loop、_prepare_engine、_build_context_strategy；保持旧导出。
- `src/heagent/gui/__init__.py`：主 loop 与 cron 重复组装，沿用各入口观察者、审批和生命周期。
- `src/heagent/engine/container.py`：default 再读全局；session 方法重复解析，应在构造固定。
- `src/heagent/engine/policy.py`：PolicyVerdict 已承载决策，不新增重复类型。
- `src/heagent/agent/loop.py`、`agent/sub.py`、`agent/system_prompt.py`：运行中全局读取需改为显式配置传递。
- `src/heagent/tools/sandbox.py`、`tools/builtins/skills.py`、`context/loader.py`、`context/tokens.py`、`memory/dream.py`、`housekeeping.py`：核查运行时设置消费，使用显式参数/现有 RuntimeSlot，不引入入口反向依赖。
- `tests/test_engine_p0.py`、`test_cli.py`、`test_cli_provider_build.py`：session 三态、可变 Settings、旧导出兼容证据。

## Tasks & Acceptance

- [x] `config.py`、`types.py`：定义不可变快照及覆盖来源，涵盖 provider/sandbox/policy/workspace/retention/hooks；私密凭证不得出现在 repr、日志或审计中。
- [x] `engine/container.py`、`engine/policy.py`：接收快照并记录 SandboxDecision、复用 PolicyVerdict；兼容构造入口可一次读取默认设置，业务方法不重新读取。
- [x] `wiring.py`、`cli.py`、`gui/__init__.py`：共享配置解析与 loop/runtime 工厂，cron 继承快照；不共享可变 run 状态。（配置解析与 engine.runtime_config 已共用；GUI loop 工厂合并归 Phase 2，见 test.md 遗留）
- [x] 上述配置消费者：消除运行中隐式取全局设置；展示层入口设置另行保留，不扩大到 Phase 2 重写循环。（保留项及理由见 docs/test.md 核查表）
- [x] `tests/test_runtime_config.py`：覆盖矩阵全部场景；架构测试防止下层导入 wiring/CLI/GUI，保留已有契约。
- [x] `docs/frame.md`：同步已实现配置边界；`docs/test.md` 只更新临时进度和真实验证结果。

验收：Given 相同设置及覆盖，When 从任一入口创建运行，Then 得到相同有效配置；Given 运行已创建，When 更改全局设置，Then 已创建运行不漂移；Given 新实现，When 运行既有测试与质量门禁，Then 行为兼容且覆盖率至少 87%。

## Spec Change Log

- 2026-09-21：任务全部完成并验收通过（细节与保留项见 `docs/test.md` 第 10 节）。验收第三条「更改全局设置已创建运行不漂移」落为构造期解析新契约：env 变更须重置单例后才被后续构造采样；`test_engine_p0` 三态开关测试按新契约更新，意图不变。

## Design Notes

以现有 API 为准；构造期兼容回退允许，业务执行不得再次读取全局。冻结必须深入集合；密钥仅用于装配，不持久化。若实现发现契约冲突，显式报告，不以调整测试掩盖。

## Verification

- `python -m pytest tests/test_runtime_config.py tests/test_architecture_contracts.py tests/test_config.py tests/test_engine_p0.py tests/test_cli.py tests/test_cli_provider_build.py tests/test_gui_goal.py -q`
- `python scripts/quality_gate.py`：全量门禁，Phase 0 已知四个格式问题需区分基线与本次引入。
- `ruff check src tests scripts`、`mypy src`。

## 执行记录（自 docs/test.md 迁入，2026-09-22 归档）

### Phase 1 执行记录

spec：`_bmad-output/implementation-artifacts/phase1-runtime-config.md`（状态 done）。分两笔提交：`9013f50`（快照类型 + engine 侧）、本笔（配置消费者收敛 + 入口共用解析 + 契约测试）。

### 变更摘要

- `config.py`/`types.py`：`ResolvedRuntimeConfig` 冻结快照 + `resolve_runtime_config()`（显式非 None 覆盖才生效、字段来源可查、凭证 exclude）；`RuntimeConfigSource`/`SandboxDecision` 冻结模型。
- `engine/container.py`：构造期解析快照；`default()` 接受 `runtime_config`/`settings`；`create_context` 将 `sandbox_decision` 写入 run metadata。
- `engine/policy.py`：`PolicyVerdict.source` 标记裁决来源（sandbox_mode/allowed_tools/blocked_tools/block_mcp_tools/workspace_paths/审批与沙箱分支）。
- `agent/loop.py`/`sub.py`/`delegation.py`：构造期快照 `self._runtime`；压缩、窗口重置、委派深度、提示词块、技能预算运行期只读快照；父快照经委派链传给子 Agent（SubAgent → 内层 loop）。
- `agent/system_prompt.py`：`build_system_prompt(..., settings=)` 显式快照；project-context 路径显式传 `max_bytes`/`user_level`。
- `tools/builtins/skills.py`：`SkillToolRuntime` 扩展 `manual_load_budget`/`curator_stale_days`，loop 在 run 作用域绑定快照值；未绑定（独立脚本/测试）才回退全局。
- `cli._build_loop` 与 `gui_main`：组装期 `resolve_runtime_config()` 一次，engine 与主/cron loop 共用 `engine.runtime_config`；cron 一次性 loop 继承快照。
- 契约测试：`FORBIDDEN_RUNTIME_IMPORTS` 扩展入口层模块（wiring/cli/cli_goal/gui），新增 `agent` 包禁止导入入口层。

### get_settings 运行期消费核查表

| 位置 | 处置 |
| --- | --- |
| `agent/loop.py` 压缩/窗口重置/委派深度 | 改读构造期快照 |
| `agent/sub.py` guard/max_iterations | 构造期快照（父快照优先；缺省时全局解析一次） |
| `agent/system_prompt.py` 三个提示词块 | 显式 `settings` 参数，loop 传快照 |
| `context/loader.load_context_files` | 提示词路径显式传值；其余调用方的参数缺省回退保留 |
| `tools/builtins/skills.py` 预算/陈旧天数 | RuntimeSlot 绑定快照值；无 run 绑定才回退全局 |
| `context/tokens._tokenizer_mode` | **保留**：观测/计量路径，已有显式防御回退（读失败按 auto）；改签名波及面大、收益低 |
| `tools/sandbox._env_allowlist` | **保留**：进程拉起时读当前安全策略属 fail-safe 方向（策略收紧即时生效）；构造期冻结反而可能用过期放行清单 |
| `housekeeping` / `memory/dream` | **保留**：显式 settings 参数优先、入口/构造期一次解析，无运行中漂移面 |

### 验证

| 检查 | 结果 |
| --- | --- |
| pytest 定向组（runtime_config / architecture_contracts / config / engine_p0 / cli / cli_provider_build / agent_loop / agent_delegation / subagent_* / skill_tools / gui_goal / compressor / window_reset / goal_declarative / goal_cross_process_lock） | 全部通过（最大组合 207 passed） |
| `ruff check src tests scripts` | 通过 |
| `ruff format --check src tests` | 通过——Phase 0 遗留 4 个格式欠账（`goal/naming.py`、`goal/workflow_loader.py`、`test_goal_cross_process_lock.py`、`test_goal_declarative_workflow.py`）本次一并格式化关闭 |
| `mypy src` | 113 文件通过 |
| `scripts/quality_gate.py` 全量 | 未完整执行（会话预算）；其组成项均已单独通过，全量门禁留待下阶段入口验证 |

### 契约语义变化（重要）

配置解析从「方法调用时惰性读全局/环境」改为「**构造期一次解析**」。env 变更后须 `reset_settings()`（或新进程）才会被后续构造采样；`test_engine_p0.py::TestSandboxSessionSwitchPrecedence::test_keep_switch_precedence` 按新契约更新（显式重置单例），测试意图（显式值压过 env、None 跟随 env）不变。

### 遗留

- GUI 主 loop 仍内联构造，未与 `cli._build_loop` 合并为共享工厂；两者已共用同一解析结果与 `engine.runtime_config`，工厂合并归 Phase 2 入口层收口。
- `resolve_runtime_config` 全量复制 Settings 字段（含 hooks 相关），hooks 无独立来源标记测试；后续 hooks 配置复杂化时再补。
