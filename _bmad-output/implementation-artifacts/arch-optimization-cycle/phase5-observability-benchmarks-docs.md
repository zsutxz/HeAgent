---
title: 'Phase 5 观测、性能和文档收口'
type: 'feature+docs'
created: '2026-09-22'
status: 'done'
baseline_commit: 'c4c6622'
review_loop_iteration: 0
context: ['{project-root}/docs/frame.md', '{project-root}/_bmad-output/implementation-artifacts/arch-optimization-cycle/arch-optimization-cycle-plan.md', '{project-root}/_bmad-output/implementation-artifacts/arch-optimization-cycle/phase4-infra-layering-concurrency.md']
---

<frozen-after-approval reason="待用户批准后冻结执行">

## Intent

问题：① 事件流**无任何耗时字段**（仅秒精度 `ts`，亚秒粒度不足），失败分类只有自由文本 `error` 字符串——provider/tool/run 各环节「慢在哪、败为何」不可观测；`workflow_runner` 全程不发事件，workflow 步骤耗时/失败完全不进事件流；② benchmark 仅 10 个（token/压缩/注册/匹配），test.md 点名的 **provider 延迟、并发工具批次、恢复性能**全部缺失，且无基线与回归阈值入口；③ 无扩展指南（「如何新增 provider/tool」只有约束规则无步骤）、无故障排查文档，README 索引缺 observability/performance 条目，事件公共契约（逐字段输入/终态/异常/持久化影响）未成表。

方案：三边界——C1 事件契约 v2（顶层 `duration_ms`/`error_kind` 字段 + emit 点接入 + workflow 事件补发，bump SCHEMA_VERSION）→ C2 benchmark 基建（4 个新基准 + 基线保存与回归阈值入口）→ C3 文档收口（扩展指南 + troubleshooting + README 索引 + frame.md 事件契约逐字段表 + 架构图核对）。

## Boundaries & Constraints

始终：行为不变优先——事件为**追加式**演进（新字段有缺省、details 自由 dict 不动），默认回归零变化；EngineEvent（engine 内部/GUI 消费面）模型不动，耗时在 emit 源头测量后经 `from_engine_event` 提升到 RunEvent 顶层；每次只动一个边界。

需要协商的预期内行为变化（均 test.md 明示授权）：
- **V1** rollout JSONL 新增 `duration_ms`/`error_kind` 顶层字段，`SCHEMA_VERSION` "1"→"2"（黄金测试同步；pydantic 默认 `extra=ignore` + 新字段缺省 ⇒ 旧文件新代码、新文件旧代码双向可读）；
- **V2** `workflow_runner.run_step` 补发 `workflow_step_started`/`workflow_step_completed`/`workflow_step_failed` 事件（现状零事件）；emit 失败/异常不改变 run_step 语义与异常传播；
- **V3** `render_event` 人读渲染追加耗时/失败分类（有值时）。

禁止：不改 EngineEvent 字段与 GUI 消费面；不改 `JsonlSink` 落盘契约（逐事件 append、LF、写失败 warning 不断 run——crash 前缀可回放语义冻结）；不引入新第三方依赖（pytest-benchmark 已在 dev）；benchmark 不进默认回归（addopts 已排除，保持）；不给 KNOWN_KINDS 加过滤语义（仍仅文档/黄金测试依据，开集不变）；不改 `ReplayEvent`/`heagent replay` CLI 签名；历史迁移叙事不入 frame.md（沿 §6 一处定义规则）。

## I/O & Edge-Case Matrix

| 场景 | 输入 | 预期 | 错误处理 |
| --- | --- | --- | --- |
| 旧 rollout（v1 无新字段） | `read_rollout` v2 代码 | `duration_ms=0`/`error_kind=""` 缺省，replay 正常 | pydantic 缺省值 |
| v2 rollout | 旧 v1 代码（假设） | `extra=ignore` 静默忽略新字段 | 前向兼容实证保留 |
| 黄金契约 | 顶层字段集 | `_EXPECTED_FIELDS` 9→11、`SCHEMA_VERSION=="2"` 断言同步 | 契约测试显性失败 |
| 未知 kind | dream/cron 等开集事件 | 透传不变（KNOWN_KINDS 收编现状 + 新增 workflow 三种，仍不过滤） | 开集语义冻结 |
| error_kind 映射 | `TimeoutError`→`timeout`、`CancelledError`→`cancelled`、`PolicyViolation`→`policy_denied`、未知工具→`unknown_tool`、其余 `Exception`→`exception` | 确定性映射表（代码单点 + frame.md 表格同源） | 未匹配一律 `exception`，不猜 |
| 耗时测量 | `perf_counter` 于 emit 源头包裹（provider 调用 / handler 执行 / run 全程 / workflow step） | `duration_ms` 整数毫秒，0=未计时 | 测量不改变原控制流 |
| workflow emit 失败 | EventBus 异常/无订阅者 | 吞掉并 warning，run_step 结果与异常传播逐字不变 | 隔离不隐藏（对齐 sink 先例） |
| benchmark 运行 | `pytest -m benchmark` | 单独可跑、不进默认回归；`--benchmark-autosave` 落 `./benchmark-data/` | 阈值入口显性文档化 |
| 文档链接 | `docs/README.md` 全部链接 | 有效（既有索引 + 新增 observability/performance/troubleshooting/extension 条目） | 链接检查 |

## Code Map

- **C1 事件契约 v2**：
  - `events/protocol.py`：`SCHEMA_VERSION="2"`；`RunEvent` 增 `duration_ms: int = 0`、`error_kind: str = ""`；`KNOWN_KINDS` + `workflow_step_started/completed/failed`（dream/cron 现状收编为文档条目，标注「引擎实发未收编」→ 收编）；新增 `error_kind_for(exc)` 确定性映射单点；`from_engine_event` 把 `details["duration_ms"]/details["error_kind"]` 提升到顶层（存在时）。
  - emit 接入（`perf_counter` 包裹 + details 注入）：`agent/loop.py`（provider_call_completed 带 duration）；`engine/executor.py`（tool_call_completed/failed 带 duration + error_kind）；`agent/run_lifecycle.py`（run_completed/run_failed 带 duration + error_kind）。
  - `engine/workflow_runner.py`：run_step 前后发 started/completed/failed（duration + error_kind），经注入或既有事件总线，emit 异常隔离。
  - `events/sink.py:render_event`：有值时追加 `[1234ms]` / `error_kind=...`。
  - `tests/test_events_jsonl.py`：`_EXPECTED_FIELDS` 11 字段、版本断言、新字段缺省/提升/映射用例；`engine` 事件契约（若 EngineEvent golden 存在则同步核查）。
- **C2 benchmark**：`tests/test_benchmarks.py` 新增 4 基准——① provider 延迟（StubProvider 固定回复，run N 迭代 wall time）；② 并发工具批次（asyncio.gather 多 sleep 工具，断言批次 wall ≈ 单工具耗时而非串行和）；③ 恢复（StubProvider 会话 resume / window_reset 耗时）；④ 事件写入吞吐（JsonlSink→tmp_path）。回归阈值入口：`pytest -m benchmark --benchmark-compare=0001_ci --benchmark-compare-fail=min:50%` 写入 test.md §13 与 docs/README；首轮 autosave 即基线（`benchmark-data/` 维持 gitignore，基线文件不强制入库——阈值命令可随时重建）。
- **C3 文档**：
  - 新 `docs/extending.md`：新增 provider（注册/config/routing/契约测试位）与新增 tool（`@tool` / registry / PolicyEngine 治理面 / path_safety / 缝注意）与新增 skill 包（SKILL.md frontmatter / workflow.md / 目录约定）三节步骤指南；链接 frame.md 硬约束。
  - 新 `docs/troubleshooting.md`：症状→诊断命令→相关模块表（启动失败 / MCP server 连不上 / 沙箱降级 / replay 解码 / 覆盖率门禁 / GUI 启动等 8-12 条）。
  - `docs/README.md`：索引补 observability（events 契约）、performance（benchmark 入口）、troubleshooting、extending 条目；压缩「Goal 工作流」占比（移 `docs/goal-workflow.md` 专题或链接 goal 文档，保持一处定义）。
  - `docs/frame.md`：新增「事件契约」小节——逐 kind 表（kind → 发射点 → details 键 → duration_ms/error_kind 语义 → 持久化影响（rollout JSONL/replay））；模块依赖 DAG 图核对 sandbox/ 包化与 mcp 新文件（C 阶段已更新清单，图与 4.12 观测节同步）；已知缺口表若因 V2 落地而闭合相应条目则同步。
- 架构契约（`tests/test_architecture_contracts.py`）：无新增（事件契约由黄金测试承载；workflow emit 不引入新依赖方向——`engine/workflow_runner` 本就在 engine 层）。

## Tasks & Acceptance

- [x] C1 事件契约 v2：字段 + emit 接入 + workflow 事件 + 渲染 + 黄金测试同步；全量默认回归原样通过（GUI 用例不动）。
- [x] C2 benchmark：4 新基准 + 阈值入口文档化；`pytest -m benchmark` 单独可跑全绿；默认回归 deselect 数 10→14 左右且其余不变。
- [x] C3 文档：extending/troubleshooting 新文档 + README 索引 + frame.md 事件契约表与架构图核对；docs 内部链接全部有效。
- [x] `docs/test.md` §14 记录执行结果；本 spec 状态 done。

验收：Given 既有 rollout 黄金测试与 GUI/事件用例，When v2 后运行，Then 原样通过；Given `pytest -m benchmark`，Then 独立运行全绿且产出基线；Given `pytest -m "not integration and not benchmark"`（默认门禁），Then 不含 benchmark；Given docs/README 链接清单，Then 逐一有效；quality_gate 全量通过（覆盖率 ≥87%）。

## Spec Change Log

- 2026-09-22：用户批准冻结并执行（「好」，V1–V3 与三边界方案全盘通过；入口全量门禁已在 c4c6622 验证）。
- 2026-09-22：C1–C3 完成，实施偏差与决策留档：
  ① `error_kind_for` 落 `events/protocol.py`（沿冻结 spec）产生**新反向边** `engine → events.protocol`
  （仅纯函数；events.protocol 运行期仅依赖 exceptions，无环）——frame.md DAG 规则与 CLAUDE.md 硬约束同步。
  ② run 耗时经 `_RunInit.started_perf` 字段携带（内部 dataclass，不落盘）；`on_run_failed` 加可选
  `duration_ms` kwarg（wrapper `_on_run_failed` 缺省 0=未计时）。
  ③ workflow emit 端口形状定为 `emit(kind, *, details=None)`；接线三层：`run_step(emit=)` →
  `application.advance(emit=)`（Phase 3 签名的追加式扩展，缺省 None 零行为变化）→
  `cli_goal._workflow_event_emitter`（绑 EngineContainer.events）。
  ④ **C2 抓出 C4 真_bug 两连**（resolve_under_root 相对 root 恒拒 / safe-open 二次 join root），
  均已修复 + 回归测试；benchmark 首次运行即验证了「基准抓数量级回归」的设计意图。
  ⑤ KNOWN_KINDS 收编 dream/cron 现状事件（开集语义不变，仍不过滤）。
  ⑥ CancelledError 并非内建名（Python 3.13 实证，asyncio 命名空间）——映射表用 `asyncio.CancelledError`。
- 2026-09-22：spec 创建（draft）。勘察结论：① `SCHEMA_VERSION="1"` 与顶层字段黄金测试已存在（`test_events_jsonl.py:33-43`）——「事件 schema 有版本」验收基线已满足，本阶段是字段演进而非新建版本机制；② 耗时/失败分类全仓为零（仅秒精度 ts + 自由文本 error），workflow_runner 零事件；③ pytest-benchmark ≥4.0 已配置（autosave/min_rounds），`-m benchmark` 现 deselect 10 个，缺 provider 延迟/并发批次/恢复；④ EngineEvent 与 RunEvent 分层清晰（GUI 读 EngineEvent、replay 读 RunEvent），耗时提升走 `from_engine_event` 单点；⑤ docs 无 extending/troubleshooting，README 索引无观测/性能条目。

## Design Notes

耗时/分类放**顶层字段**而非 details 键：`details` 是自由 dict（本就「什么都能塞」，无统一性可言），「统一事件字段」的意图即把高频查询面（慢在哪/败为何）提升为可枚举契约——黄金测试锁字段集正是为此存在的机制。error_kind 用**封闭映射 + exception 兜底**而非开放枚举：映射表单点代码 + frame.md 表格同源，未匹配不猜（显性 `exception`）。workflow 事件最小化为 started/completed/failed 三种、经既有 EventBus 语义（emit 异常隔离对齐 sink 先例「可观测性不得改变业务控制流」）。benchmark 阈值采用 pytest-benchmark 原生 compare-fail 机制而非自建断言——避免重复造轮子，且 `min:50%` 宽松阈值明确「防数量级回归，不做微优化门禁」（test.md §7.3：以基准建立基线，避免无证据优化）。

## Verification

- `python -m pytest tests/test_events_jsonl.py tests/test_benchmarks.py tests/test_engine_workflow.py tests/test_gui_tool_state.py tests/test_architecture_contracts.py -q`（文件名以实际存在为准）
- `python -m pytest -m benchmark -q`（独立可跑）与默认门禁 deselect 核对
- `python scripts/quality_gate.py` 全量（每 C 边界 + 最终）
- `ruff check src tests scripts`、`ruff format --check src tests`、`mypy src`
- docs 链接人工核对（docs/README 索引 → 目标文件存在）

</frozen-after-approval>

## 执行记录（自 docs/test.md 迁入，2026-09-22 归档）

### Phase 5 执行记录

spec：`_bmad-output/implementation-artifacts/phase5-observability-benchmarks-docs.md`。基线提交 `c4c6622`。

### 入口全量门禁（2026-09-22）

c4c6622 上全量默认回归全绿（Phase 4 终态即 Phase 5 基线）。

### C1 事件契约 v2（已完成）

- `SCHEMA_VERSION` "1"→"2"；`RunEvent` 顶层 +`duration_ms`/`error_kind`（黄金测试 `_EXPECTED_FIELDS` 9→11 字段同步）。
  发射点把两键放 `EngineEvent.details`（EngineEvent 模型/GUI 面冻结），`from_engine_event` 提升到顶层并摘除
  （非 int duration 缺省 0）；v1 rollout 双向可读（缺省读 / extra=ignore，溯源版本保留）。
- emit 接入：provider_call_completed（中间件链整体耗时）、tool_call_completed/failed（耗时+分类，
  DIRECT/SANDBOX 两路径）、run_completed/run_failed（run 全程耗时，经 `_RunInit.started_perf` 携带起点）。
- `workflow_runner.run_step` 补发 `workflow_step_started/completed/failed`（`emit` 注入端口，缺省 None=零
  行为变化；emit 异常隔离 warning）：耗时 + `error_kind_for` 封闭映射（timeout/cancelled/policy_denied/
  safety_blocked/tool_error/exception 兜底，explicit 覆盖 unknown_tool）。
  接线：`application.advance(emit=)` → `cli_goal._workflow_event_emitter`（绑 EngineContainer.events）。
- KNOWN_KINDS 收编 dream/cron 现状 + workflow 三种（仍不过滤）；`render_event` 有值时追加 `[Nms]`/`error_kind=`。
- 实测红三连：CancelledError 并非内建名（3.13 实证，改 asyncio 导入）；`_emit_step_event` 误加 `self.` 前缀；
  goal 测试 StubRunner.run_step 补 emit 形参。
- **新增反向边（留档）**：`engine → events.protocol`（仅 `error_kind_for` 纯函数，运行期 events 仅依赖
  exceptions，无环）——frame.md DAG 规则与 CLAUDE.md 硬约束同步。

### C2 benchmark 基建（已完成）

- 新增 4 基准（`tests/test_benchmarks.py`，`-m benchmark` 独立运行）：provider 延迟（StubProvider 单迭代
  完整 loop.run）、并发工具批次（gather×8 sleep，断言 wall<0.10s 数量级守护）、会话恢复（SessionStore 20 条
  历史完整 run）、事件写入吞吐（JsonlSink rollout 50 事件）。
- 回归阈值入口：`pytest -m benchmark -q --benchmark-compare=0001 --benchmark-compare-fail=min:50%`
  （数量级守护，非微优化门禁；基线 autosave `./benchmark-data/`，不强制入库）。
- **benchmark 抓出 C4 真 bug 两连**（显性失败的价值）：① `resolve_under_root` 对相对 root 恒拒
  （绝对化候选 vs 未 resolve root）——生产默认 `SkillStore(base_dir=".heagent/skills")` 即相对根，已修
  （root 一并 resolve 后比较）+ 回归测试；② safe-open 内核对「已含 root 前缀的相对路径」二次 join root
  （root/name → root/root/name）——kernel 语义改为「绝对或 cwd 相对 + root 围栏校验」，裸资源名显性报越界。

### C3 文档收口（已完成）

- 新 `docs/extending.md`（新增 Provider/Tool/Skill 包步骤 + 架构契约自检）、`docs/troubleshooting.md`
  （16 症状表 + 诊断命令速查，含 benchmark 阈值入口）。
- `docs/README.md`：「Goal 工作流」70% 长文迁 `docs/goal-workflow.md` 专题（一处定义）；索引补
  观测/性能/扩展/排查条目；快速定位表补四行。
- `docs/frame.md` 新增 4.15 事件契约（逐字段表 + 逐 kind 发射点/details/耗时分类表 + 持久化影响）；
  DAG 规则补 events 边。CLAUDE.md engine 依赖行同步。
- docs 相对链接核查：全部有效。

### 收尾门禁（Phase 5 全边界后）

quality_gate 全量绿；`pytest -m benchmark` 14 全绿（10 既有 + 4 新增）；默认回归 deselect 数不变
（benchmark 均不进默认回归）。
