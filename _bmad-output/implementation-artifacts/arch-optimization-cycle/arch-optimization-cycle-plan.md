---
title: '架构优化周期总方案（归档）'
type: 'cycle-plan'
status: 'done'
created: '2026-09-21'
completed: '2026-09-22'
note: '原 docs/test.md（gitignore 未入库）的 §1-8 迁入。6 阶段全部完结；逐阶段执行记录在各 phase 归档文件内。'
---

# HeAgent 架构与代码库优化方案（周期总方案）

## 1. 目标与约束

本轮优化的目标是让 HeAgent 在继续支持异步 Agent Loop、多 Provider、工具安全链、MCP、记忆、声明式 `/goal` workflow 和 sandbox 的前提下，具备以下特征：

1. 依赖方向可由测试自动证明，入口层只负责组装，不承载领域规则。
2. Agent Loop、workflow、sandbox、MCP 和持久化的职责边界清晰，新增能力优先通过接口注入。
3. 运行状态、事件、工具执行结果和 artifact 的数据契约统一，错误显式返回或抛出，不以静默回退掩盖配置问题。
4. 测试按单元、契约、集成和外部依赖分层，质量门禁可重复执行。
5. 文档有单一事实来源，现状、目标和迁移记录分开，删除失效链接和过期架构描述。

约束保持不变：Python 3.11+、asyncio 为主、跨模块数据优先使用 `types.py` 的模型、工具链遵守 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler，sandbox 仍是 defense-in-depth 而非 OS 安全边界。

## 2. 当前基线

### 2.1 规模与质量基线

- `src/heagent/` 当前 113 个 Python 文件、24,114 物理行；`tests/` 103 个 Python 文件（包含 fixture 和包入口）。原稿的 18,222 行受读取编码和统计口径影响，已纠正。
- `pytest --collect-only -q` 当前收集 2,037 个测试，默认配置排除 14 个 `integration`/`benchmark` 测试。
- 现有质量门禁位于 `scripts/quality_gate.py`，顺序为 workflow smoke、默认回归与覆盖率（门槛 87%）、Ruff lint、Ruff format、mypy。
- 已有架构契约测试覆盖运行期反向依赖、`TYPE_CHECKING` 导入、frontmatter 集中解析和时间戳格式；这些测试应继续作为架构演进的硬约束。

### 2.2 已确认的结构

当前依赖主线可概括为：

```text
types / exceptions / config / persist / roles
        ↓
providers / tools / context / events / memory / cron
        ↓
engine（policy、executor、store、ledger、workflow）
        ↓
agent（loop、sub-agent、delegation）
        ↓
cli / gui / __main__
```

`EngineContainer` 已经承担运行时服务组装，`AgentLoop` 负责模型调用、工具批次、上下文管理、恢复和流式事件，`WorkflowRunner` 负责声明式 story 执行，`ToolExecutor` 负责策略、sandbox、hooks 和 ledger 之间的衔接。`tests/test_architecture_contracts.py` 与 `tests/test_artifact_contracts.py` 已经是重要的契约入口。

### 2.3 主要问题

| 优先级 | 问题 | 证据/影响 |
| --- | --- | --- |
| P0 | 入口编排职责过重 | `cli.py` 与 `cli_goal.py` 同时处理命令解析、依赖组装、workflow 路由、持久化和展示适配；入口改动容易影响多个运行模式。 |
| P0 | 核心循环状态面过大 | `agent/loop.py` 1,189 物理行，混合 run 生命周期、stream、resume、pause、steering、tool 批处理、上下文重置和运行后产物；行为契约难以局部验证。 |
| P0 | 安全策略存在多处配置入口 | `EngineContainer.default()`、`PolicyEngine`、`ToolExecutor`、sandbox backend 和 CLI 参数共同决定授权与隔离；缺少统一的“已解析运行配置”模型时，容易出现配置覆盖顺序不透明。 |
| P1 | workflow 领域与 CLI 耦合 | `/goal` 的大量确定性规则仍在 `cli_goal.py`，workflow 资源和 checkpoint 虽在 `engine/`，但调用边界不够薄，难以复用到 GUI/cron/API。 |
| P1 | 基础设施模块偏大 | `tools/sandbox.py`、`tools/mcp/manager.py`、`memory/skills.py` 集中承载进程管理、协议适配、资源安全和存储更新，变更的回归半径较大。 |
| P1 | 运行模型与事件模型存在并行概念 | run snapshot、checkpoint、ledger、events、tool activity 各自持有部分状态；恢复、幂等和观测字段需要一个明确的关联键与生命周期说明。 |
| P2 | 文档存在重复和失效风险 | `docs/frame.md` 超过 1,100 物理行并混合现状、历史迁移和实现细节；Phase 0 已补齐索引与维护责任、独立归档参考来源；详细内容持续随模块变更核验。 |

## 3. 目标架构

### 3.1 分层与依赖规则

将代码边界固定为五层，并把组合根限制在入口层：

```text
domain      = types、exceptions、frontmatter、纯规则和值对象
adapters    = providers、MCP transport、sandbox backend、文件/网络适配
application = agent use-case、workflow use-case、memory use-case、run orchestration
runtime     = engine policy/executor/store/ledger/events/checkpoint
entrypoints = cli、gui、cron command、__main__、wiring
```

规则如下：

- `domain` 不导入其他业务层；只允许标准库和纯数据依赖。
- `adapters` 只实现协议，不导入 `cli`、`gui` 或 `AgentLoop`。
- `application` 通过 Protocol/数据模型使用 adapter，不直接创建 SDK client、文件锁或子进程。
- `runtime` 提供可注入的运行服务；`EngineContainer` 是 composition root 的运行时部分，不向入口暴露内部实现细节。
- `entrypoints` 只解析输入、构建依赖、调用 application use-case 和渲染输出。
- 所有跨边界契约必须有一个定义位置；禁止重复定义 frontmatter、时间戳、工具结果和 workflow 状态。

架构契约测试应由当前的 `test_architecture_contracts.py` 扩展为包级规则表，新增包或例外必须同时更新规则、文档和测试，而不是依赖约定记忆。

### 3.2 运行时对象模型

建立四个明确对象并使用同一 `run_id` 关联：

1. `RunRequest`：一次运行的输入、session、workspace、策略和 provider 选择。
2. `RunState`：循环中的可恢复状态，包括消息窗口、迭代、待执行调用和 workflow checkpoint 引用。
3. `RunResult`：完成、失败、取消、等待审批等终态，以及 token、错误和产物摘要。
4. `RunEvent`：面向 CLI/GUI/JSONL/审计的不可变事件，工具调用、策略判定、sandbox、checkpoint 和 provider 失败统一携带 `run_id`、`parent_run_id`、`sequence`。

`RunStore` 保存可恢复状态，`ExecutionLedger` 只负责工具调用幂等和 lease，`EventBus` 只负责事件投递；三者不得互相兼任。workflow checkpoint 只保存 workflow 状态及其版本，不复制完整 run snapshot。

### 3.3 核心模块拆分方向

| 当前模块 | 目标拆分 | 拆分原则 |
| --- | --- | --- |
| `agent/loop.py` | `run_lifecycle`、`tool_batch`、`context_runtime`、`stream_runtime`、`resume_runtime` | `AgentLoop` 保留 façade 和依赖注入；每个策略单独可测。 |
| `cli.py` | `cli/dependencies.py`、`cli/chat.py`、`cli/render.py`、`cli/commands.py` | 命令解析、对象组装、运行控制、展示分离；保留兼容入口。 |
| `cli_goal.py` | `goal/application.py`、`goal/gates.py`、`goal/persistence.py`、`goal/commands.py` | workflow 规则下沉到 application/domain，CLI 只适配 Click。 |
| `tools/sandbox.py` | `sandbox/contracts.py`、`sandbox/process.py`、`sandbox/firejail.py`、`sandbox/winjob.py`、`sandbox/session.py` | 进程监督、平台后端、会话目录和配置解析互不耦合。 |
| `tools/mcp/manager.py` | `mcp/client.py`、`mcp/lifecycle.py`、`mcp/registry_bridge.py`、`mcp/resources.py` | transport/session、工具映射、资源读取和 registry 注入分层。 |
| `memory/skills.py` | `skill_models.py`、`skill_catalog.py`、`skill_store.py`、`skill_rewrite.py` | 解析、检索、持久化更新和 TOCTOU 防护分别拥有测试边界。 |

拆分以行为不变为前提，先移动并保留兼容导出，再删除旧实现；每次只改变一个边界，避免同时改变状态模型和模块路径。

## 4. 分阶段实施计划

### Phase 0：基线冻结与文档治理（P0）

- 固定 `quality_gate.py`、架构契约测试和测试收集数作为迁移基线。
- 记录公共类型、运行状态、事件和 workflow 状态的现有版本契约与迁移边界。新增序列化字段移至后续代码阶段，须附旧数据兼容测试，不能作为文档整理顺带修改。
- 重写 `docs/README.md` 为文档索引：架构、开发、测试、部署、设计、迁移和历史记录分栏。
- 将 `docs/frame.md` 拆成“当前架构”和“历史决策/迁移记录”；保留链接，不复制全文。
- 校验所有 docs 链接、命令和环境变量名称；将 `langchain-migration-feasibility.md`、`news.md` 标为有明确维护者的专题/历史文档。

验收：文档链接检查无失效项；架构图与实际 import 契约一致；质量门禁命令在干净环境中可执行。

执行说明：本次采用现有开发环境验证，不声明完成全新环境验收；详细限制与待办见第 9 节。

### Phase 1：组合根和运行配置收敛（P0）

- 新增不可变的 `ResolvedRuntimeConfig`，一次性解析 provider、sandbox、policy、workspace、retention 和 hooks 配置。
- 将 `wiring.py` 与 CLI/GUI 共用的依赖组装集中到 entrypoint composition root；下层只接收已构造对象。
- 为 sandbox/policy 建立显式的 `SandboxDecision`/`PolicyDecision` 结果模型，记录来源和最终有效值。
- 禁止在业务方法中隐式调用 `get_settings()`；保留明确的入口注入和测试 fixture。

验收：新增配置覆盖顺序测试；CLI、GUI、cron 使用相同解析结果；架构测试禁止下层导入入口配置模块。

### Phase 2：Agent Loop façade 化（P0）

- 抽出 run 生命周期、工具批次执行、上下文策略、stream 适配和 resume 适配器。
- 让 `AgentLoop` 只协调 use-case，保留现有 `run()`、`run_stream()`、`resume()`、`resume_stream()` 公共接口。
- 将 pause、steering、follow-up 统一为可测试的事件/消息端口，明确取消传播和异常边界。
- 以状态转换表替代散落布尔标志；终态只能由一个 reducer 写入。

验收：现有 agent、streaming、window reset、session resume、steering 测试全部通过；新增状态转换契约测试；核心 façade 行数和分支数下降，但不以牺牲可读性为目标。

### Phase 3：Workflow 与运行时状态解耦（P1）

- 将 `/goal` 的确定性校验、gate、story 选择和 checkpoint 推进放入 `goal/application.py` 与 `engine/workflow` 契约。
- CLI、GUI、cron 只调用同一个 workflow use-case，禁止各入口复制推进逻辑。
- 明确 workflow checkpoint 与 run snapshot 的引用关系、幂等键和恢复语义；损坏状态必须显式失败。

验收：goal smoke、workflow runner、artifact contract、checkpoint 和跨进程锁测试通过；同一 workflow use-case 可在无 Click 环境下运行。

### Phase 4：基础设施分层与并发边界（P1）

- 按目标架构拆分 sandbox、MCP、skills；为每个 backend/transport 定义最小 Protocol。
- 统一子进程取消、超时、kill/reap、输出截断和资源清理的错误语义。
- 统一 MCP server 生命周期与工具注册/注销，单 server 失败隔离但不隐藏发现错误。
- 为 skill 资源读取保留“解析后安全打开”的单一入口，继续覆盖 TOCTOU、路径逃逸和并发替换。

验收：sandbox、winjob、MCP、skill package、path safety 测试通过；在 Windows 和 Linux CI 上分别执行平台后端测试；资源泄漏和孤儿进程检查纳入集成门禁。

### Phase 5：观测、性能和文档收口（P2）

- 统一事件字段和 JSONL schema，补充 provider、tool、sandbox、workflow 的耗时和失败分类。
- 增加基于固定 StubProvider 的延迟、token、并发工具批次和恢复性能基准；benchmark 不进入默认回归但必须可单独运行。
- 更新架构图、模块责任表、扩展指南和故障排查；每个公共接口写明输入、终态、异常和持久化影响。

验收：事件 schema 有版本；benchmark 有基线和回归阈值；文档索引、架构契约和质量门禁全部通过。

## 5. 测试与质量策略

### 5.1 测试分层

| 层级 | 内容 | 运行方式 | 目标 |
| --- | --- | --- | --- |
| 单元 | 纯解析、状态 reducer、policy、provider 转换、token 计算 | 默认回归 | 快速、确定、无网络 |
| 契约 | Protocol、导入方向、事件 schema、artifact 层级、配置解析 | 默认回归 | 防止边界漂移 |
| 组件 | Agent Loop + StubProvider、ToolExecutor + fake backend、workflow use-case | 默认回归 | 验证跨模块意图 |
| 集成 | MCP、真实 sandbox backend、跨进程锁、文件系统并发 | `pytest -m integration` | 验证外部边界和平台行为 |
| 性能 | token、并发工具、长 workflow、恢复耗时 | `pytest -m benchmark` | 监测趋势，不作为功能通过条件 |
| CLI/UI 烟测 | `python -m heagent`、`/goal`、JSONL 输出 | smoke job/人工 | 验证入口装配和用户可见错误 |

### 5.2 必须新增的测试意图

- 配置解析：CLI 参数、环境变量和默认值的优先级，以及非法值的显式失败。
- 状态转换：成功、失败、取消、等待审批、暂停、恢复和损坏 checkpoint 的唯一终态。
- 幂等性：相同 `run_id + tool_call_id` 不重复执行；策略收紧后不得直接复用不再允许的缓存。
- 并发性：工具批次结果保持调用顺序；ledger lease、workflow 锁和文件写入在并发下不丢更新。
- 安全性：路径逃逸、SSRF、敏感环境变量、sandbox backend 不可用时的降级和授权元数据。
- 文档契约：代码中的公共命令、环境变量、模块路径和 docs 索引互相可验证。

测试验证意图而非仅验证“没有抛异常”。对安全和恢复场景，断言拒绝原因、状态、事件和持久化结果；对外部依赖，使用 fake/stub 控制失败类型和时序。

### 5.3 质量门禁调整

短期保持 `scripts/quality_gate.py` 的 fail-fast 顺序不变。Phase 0 完成后增加：

```text
pytest tests/test_architecture_contracts.py tests/test_artifact_contracts.py -q
pytest tests/test_goal_workflow_smoke.py -q
pytest -m "not integration and not benchmark" --cov=heagent --cov-fail-under=87
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
```

门禁失败必须报告具体阶段、命令和首个失败测试；禁止在入口层捕获并吞掉质量检查异常。覆盖率只作为下限，不替代契约测试和场景测试。

## 6. 文档整理方案

文档采用“一处定义、其他处链接”的规则：

- `docs/README.md`：唯一索引，说明读者路径和文档维护责任。
- `docs/frame.md`：当前实现架构、依赖规则、运行数据流和公共契约；不再承载完整历史时间线。
- `docs/design.md`：产品/交互设计原则和非代码决策。
- `docs/iteration.md`：已完成周期、迁移记录和决策链接，只保留摘要。
- `docs/test.md`：本方案、测试分层、质量门禁和后续验收记录。
- 专题文档：只保留仍有维护价值的 provider、LangChain、部署和安全专题，并在文件头声明状态、适用版本和维护者。
- `_bmad-output/`：规划产物的事实来源；docs 只链接已确认的结论，不复制 story 全文。

每次代码变更至少同步检查：模块责任、公共入口、配置变量、错误语义、测试命令和文档链接。架构变化先更新本方案或对应契约，再实现代码。

## 7. 风险与决策点

1. **兼容性风险**：模块移动会影响内部导入。先保留 re-export 和弃用周期，完成调用方迁移后再删除。
2. **状态迁移风险**：run/checkpoint/ledger 数据可能来自旧版本。必须提供版本字段、读取兼容和显式迁移失败信息。
3. **性能风险**：拆分后的事件和 reducer 可能增加对象创建。用 benchmark 建立基线，避免无证据优化。
4. **平台差异**：Firejail、Windows Job Object 和 passthrough 的安全能力不同。配置解析必须输出实际 backend 和授权结果，文档不得把降级描述成隔离成功。
5. **范围风险**：本计划不包含更换 LLM SDK、重写 CLI/UI 或引入新的持久化数据库；这些属于单独的技术决策。

## 8. 完成定义

本方案对应的架构优化完成需同时满足：

- 依赖方向、frontmatter、事件和 artifact 契约由自动化测试保护。
- CLI、GUI、cron 共享 application/runtime use-case，不复制 workflow 或 run 编排。
- `AgentLoop` 对外 API 保持兼容，内部策略可独立测试，恢复和取消语义有明确状态转换测试。
- sandbox、MCP、skills 的平台/协议边界可替换，失败原因和资源清理可观察。
- 默认质量门禁、integration、benchmark 和 CLI smoke 均有明确入口及环境前提。
- `docs/README.md` 中所有链接有效，`frame.md` 与代码契约一致，历史内容不会冒充当前实现。
- 每个阶段都有变更记录、测试证据和已知限制，未完成项进入明确的 deferred work，而不是留在代码注释中。
