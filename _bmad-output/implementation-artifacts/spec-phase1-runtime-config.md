---
title: 'Phase 1 运行配置快照与统一装配'
type: 'refactor'
created: '2026-09-21'
status: 'in-progress'
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

- [ ] `config.py`、`types.py`：定义不可变快照及覆盖来源，涵盖 provider/sandbox/policy/workspace/retention/hooks；私密凭证不得出现在 repr、日志或审计中。
- [ ] `engine/container.py`、`engine/policy.py`：接收快照并记录 SandboxDecision、复用 PolicyVerdict；兼容构造入口可一次读取默认设置，业务方法不重新读取。
- [ ] `wiring.py`、`cli.py`、`gui/__init__.py`：共享配置解析与 loop/runtime 工厂，cron 继承快照；不共享可变 run 状态。
- [ ] 上述配置消费者：消除运行中隐式取全局设置；展示层入口设置另行保留，不扩大到 Phase 2 重写循环。
- [ ] `tests/test_runtime_config.py`：覆盖矩阵全部场景；架构测试防止下层导入 wiring/CLI/GUI，保留已有契约。
- [ ] `docs/frame.md`：同步已实现配置边界；`docs/test.md` 只更新临时进度和真实验证结果。

验收：Given 相同设置及覆盖，When 从任一入口创建运行，Then 得到相同有效配置；Given 运行已创建，When 更改全局设置，Then 已创建运行不漂移；Given 新实现，When 运行既有测试与质量门禁，Then 行为兼容且覆盖率至少 87%。

## Spec Change Log

## Design Notes

以现有 API 为准；构造期兼容回退允许，业务执行不得再次读取全局。冻结必须深入集合；密钥仅用于装配，不持久化。若实现发现契约冲突，显式报告，不以调整测试掩盖。

## Verification

- `python -m pytest tests/test_runtime_config.py tests/test_architecture_contracts.py tests/test_config.py tests/test_engine_p0.py tests/test_cli.py tests/test_cli_provider_build.py tests/test_gui_goal.py -q`
- `python scripts/quality_gate.py`：全量门禁，Phase 0 已知四个格式问题需区分基线与本次引入。
- `ruff check src tests scripts`、`mypy src`。
