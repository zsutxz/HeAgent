---
title: 'Phase 3 Workflow 与运行时状态解耦'
type: 'refactor'
created: '2026-09-21'
status: 'done'
baseline_commit: '71d1674'
review_loop_iteration: 0
context: ['{project-root}/docs/frame.md', '{project-root}/docs/test.md', '{project-root}/_bmad-output/implementation-artifacts/spec-phase2-loop-facade.md']
---

<frozen-after-approval reason="待用户批准后冻结执行">

## Intent

问题：`cli_goal.py` 991 物理行混合三类职责——① 确定性工作流编排（workflow 校验、gate 渲染、story 选择、checkpoint 恢复与推进、prompt 装配）；② Click I/O 渲染（约 30 处 `click.echo` 用户文案散落在编排分支内）；③ 入口装配（dispatch / cron / mutex）。后果：确定性内核无法在无 Click 环境运行与测试；GUI 只能靠 stderr 重定向转发获取进度（gui/screens/chat.py 自述「文案冻结」）；推进逻辑对 CLI/GUI/cron 三个入口只有事实上的单点、无契约钉死（test.md §4-Phase 3 P1）。

方案：新增 `goal/application.py`（入口层子包，先例 goal/document.py）承载 **click-free 确定性内核 + 结构化 outcome**；`_goal_declarative_advance` 收缩为「准备 → 注入端口 → 调 use-case → 渲染 messages」薄壳；engine/workflow 形式化 `StepExecutor` 端口契约；架构契约测试钉死「application 不依赖 Click 与入口模块」「入口不复制推进逻辑」。

## Boundaries & Constraints

始终：行为不变优先——用户可见 stderr 文案逐字保留（测试 capsys 断言多处钉死原文）；monkeypatch 缝原位保留（见 Code Map 缝清单）；每次只动一个边界（C1 纯移动 → C2 结构化 → C3 契约钉死）；分层沿用 goal/__init__ 声明（入口层子包，依赖 engine/memory/persist/context 等下层，不被下层导入）。

需要协商：无预期行为变化。若实现中发现必须变更（如消息必须分批渲染才能保序），在 Spec Change Log 留档并停下确认。

禁止：不改 checkpoint 落盘格式与 `workflow.json` schema（归 Phase 5）；不改 `WorkflowRunner.run_step`/`from_checkpoint`/`persist_state` 语义；不动 `_GOAL_LOCK_PATH`/`_GOAL_LOCK_TIMEOUT`/`_goal_auto_lock` 的模块位置；不把 GUI 的 stderr 转发升级为原生渲染（行为冻结，收益留待后续周期）；不引入新第三方依赖；不把 docs/test.md 加入 Git。

## I/O & Edge-Case Matrix

| 场景 | 输入 | 预期 | 错误处理 |
| --- | --- | --- | --- |
| 兼容导入 | 既有测试 `from heagent.cli_goal import _goal_declarative_runner/_goal_declarative_prompt/_GoalAdvanceContext/_GOAL_FAILED/...` | re-export 全部保持，`cli._goal_runner is cli_goal._goal_runner` 身份断言不变 | 禁止一次性删除旧符号 |
| 无 active goal / 损坏 require.md / 损坏 checkpoint | prepare 各失败分支 | message 收集后由 CLI 原文渲染，返回 `_GOAL_FAILED` | 显性失败，不静默降级 |
| checkpoint 配置不匹配 | `restore_runner` 匹配规则落空且存在历史 checkpoint | `WorkflowCheckpointError` 显性抛出（现状语义，补契约测试钉死） | 不回退 legacy 流 |
| WAITING_USER checkpoint 决策 | manual 模式 → 注入 confirm 端口；auto 模式 → 直接 resume+persist | 决策顺序与现状一致；中断回调不视为隐式批准 | EOF/Ctrl+C → waiting |
| use-case 无 Click 运行 | `goal/application.py` import 图 | AST 契约：禁止 `click`/`heagent.cli*`/`heagent.gui` 运行期导入 | 契约测试显性失败 |
| 入口复制推进 | CLI/GUI/cron 推进路径 | 三入口仍收敛到 `cli_goal._goal_runner` / `_goal_cron_advance` → 同一 use-case；契约测试钉死 engine/workflow 不反向依赖 goal | — |

## Code Map

- 新 `src/heagent/goal/application.py`（预计 ~400 行）：
  - 纯函数迁入（C1）：`validate_goal_workflow`、`checkpoint_mode(workflow, fallback)`、`open_question_mode(workflow, fallback)`（settings 值由调用方注入，模块内禁 `get_settings`）、`open_question_policy`、`gate_requirements`、`dedupe_inputs`、`render_template`、`declarative_prompt`、`role_instructions(workflow, step_name)`、`resolve_skill_package(skill_id)`（`_GOAL_SKILLS_ROOT` 常量随迁）、`load_stories`、`checkpoint_store(goal_dir)`、`restore_runner(store, workflow, goal_dir)`（checkpoint↔workflow.json↔current 指针↔require.md 引用关系与恢复语义写入 docstring）、`_GoalAdvanceContext` 随迁。
  - use-case（C2）：`GoalMessage(level, text)` / `GoalAdvanceOutcome(status, messages)` Pydantic 模型（跨模块数据禁裸 dict）；`async advance(context, execute_step, *, confirm_checkpoint, load_project_context) -> GoalAdvanceOutcome` 承接现 `_goal_declarative_advance` 主循环（inputs 装配、story 选择、run_step、checkpoint 决策、BLOCKED 指路文案）；`pause_resume` 决策内核同批迁入；`GoalAdvanceStatus` StrEnum（advanced/done/failed/waiting，值与现 `_GOAL_*` 常量一致）。
- `src/heagent/cli_goal.py`（991 行，预期收缩 ≤600）：保留全部缝宿主与渲染薄壳——`_goal_session`、`_goal_execute_step`（缝链：session 的调用方必须同模块）、`_goal_declarative_prepare`（缝：签名 `tuple[None, ctx] | tuple[str, None]` 不变）、`_goal_declarative_advance`（缝：薄壳化，渲染 messages → click.echo(err=True)，返回 status 字符串）、`_goal_declarative_workflow`/`_goal_workflow_package`（get_settings 入口点）、`_goal_checkpoint_prompt`（click.confirm TTY 端口实现）、dispatch/usage/reset/auto/cron/mutex/`_goal_runner`；其余经 re-export 保持命名空间。
- `src/heagent/engine/workflow_runner.py`：`StepExecutor` Protocol 形式化（现 run_step 回调的隐式契约显名），run_step 类型标注引用之；runner 语义不动。
- 缝清单（搬移红线，grep 已核）：
  | 缝 | patch 处 | 调用方（须同模块） |
  | --- | --- | --- |
  | `heagent.cli_goal._goal_session` | 3 测试文件 5 处 | `_goal_execute_step` |
  | `cli_goal._goal_declarative_advance` | 2 处 | dispatch/run/new/cron_advance |
  | `cli_goal._goal_declarative_prepare` | 1 处 | advance 薄壳 |
  | `cli_goal._goal_runner` | GUI 3 处 + 锁测试 | cli.py / gui chat.py 惰性导入 |
  | `cli_goal._goal_auto_goal_id` / `_goal_cron_advance` | wiring 测试 | `wiring.build_cron_job_runner` |
  | `cli_goal._GOAL_LOCK_TIMEOUT` / `_GOAL_LOCK_PATH` / `_goal_auto_lock` | 锁测试 | `_goal_mutex` |
- 架构契约（C3，`tests/test_architecture_contracts.py` 扩展）：① `goal/application.py` 运行期禁止导入 `click` / `heagent.cli` / `heagent.cli_goal` / `heagent.gui*`（AST 全路径扫描，沿 Phase 2 手法）；② `engine/*` 运行期禁止导入 `heagent.goal*`（反向依赖钉死）；③ use-case 无 Click 可运行由 ① 的导入图断言承载。

## Tasks & Acceptance

- [x] C1 内核抽取：上述纯函数 + 常量迁 `goal/application.py`，cli_goal re-export；行为零变化，goal 全系测试原样通过（95 passed）。
- [x] C2 advance 结构化：`GoalAdvanceOutcome`/`advance()`/`pause_resume` 内核迁入；`_goal_declarative_advance`/`_goal_declarative_pause_resume` 薄壳化（渲染 + 端口注入）；stderr 文案逐字保留。
- [x] C3 契约钉死：架构契约 ① 落地（click-free AST 契约）；② 已由既有 `FORBIDDEN_RUNTIME_IMPORTS["engine"]` 覆盖不重复；恢复语义契约测试补齐（不匹配 → WorkflowCheckpointError）；`goal/__init__.py` 与 frame.md 模块地图同步。
- [x] `docs/frame.md` 调用链与模块清单更新；`docs/test.md` §12 记录执行结果；本 spec 状态 done。

验收：Given 既有 goal smoke / workflow runner / artifact contract / checkpoint / 跨进程锁测试，When 拆分后运行，Then 原样通过且无跳过；Given `goal/application.py`，When AST 扫描 import 图，Then 无 click 与入口模块依赖；Given cli_goal 薄壳化，When 统计行数，Then 较基线 991 行显著下降且缝全部原位；quality_gate 全量通过（覆盖率 ≥87%）。

## Spec Change Log

- 2026-09-21：C1/C2/C3 完成。实施偏差与决策留档：
  ① engine `StepExecutor` Protocol **未新增**——`WorkflowCallback`/`StoryWorkflowCallback` 类型别名已显名承载 run_step 回调契约，再包一层 Protocol 属纯 ceremony（简约至上）；application 侧以 `StepExecutor = Callable[[inputs, step, story], Awaitable[WorkflowStepResult]]` 别名承载入口端口形状。
  ② `GoalMessage(level, text)` 简化为 `messages: list[str]`（文案为完整行）——现渲染面全部同走 stderr，level 无消费者，不为想象需求加字段（GUI 原生渲染属后续周期，届时再加）。
  ③ `_goal_declarative_runner` 签名保持 `(workflow, goal_dir)` 整体迁入（spec 草案曾拟拆 store 参数），恢复语义 docstring 在此显式化；checkpoint store 工厂独立为 `checkpoint_store(goal_dir)`。
  ④ cli_goal 680 行 > 预估 ≤600：超量为 dispatch/usage/auto/cron 入口编排与缝注释（属入口职责，不属确定性内核），为凑数而压缩会伤可读性——验收「显著下降且缝原位」满足（991→680，-31%）。
  ⑤ advance 内嵌 run_step 回调经 `functools.partial` 桥接（B023 循环闭包晚绑定歧义 + C901 复杂度由 `_advance_checkpoint_decision` helper 拆出消解）。
  ⑥ `_goal_record_user_response`/`_goal_user_responses` 在 cli_goal 失去内部调用点，靠 `__all__` 钉住 re-export（测试仍经 cli_goal 访问；沿 Phase 2 loop.py `__all__` 先例解 F401 × PLC0414 × mypy 三方交集）。
  ⑦ naming.py 的 click.echo（LLM 命名失败回退提示）属入口侧提示，不纳入 use-case click-free 契约（契约只钉 application.py）。

- 2026-09-21：用户批准冻结并执行（入口全量门禁先行：71d1674 上全量测试通过）。
- 2026-09-21：spec 创建（draft）。勘察结论：① 缝清单全量 grep 核定（上表），`_goal_declarative_runner`/`_goal_declarative_prompt` 等只有导入依赖无 patch 缝，可安全迁出 + re-export；② GUI stderr 转发现状冻结——升级为原生渲染属行为变化，超出「行为不变优先」，排除出本阶段；③ checkpoint 损坏显性失败已在 `WorkflowCheckpointStore`（load/list/save 三处 `WorkflowCheckpointError`）落地，本阶段补契约测试而非新机制。

## Design Notes

端口划分沿 Phase 2 message_ports 先例做**最小协议**：`execute_step`（LLM 会话缝，必须留 cli 层）、`confirm_checkpoint`（click.confirm TTY 实现）、`load_project_context`（cwd 锚定属入口）三者注入，其余（inputs 装配、story 加载、checkpoint 决策、状态机）全部确定性收敛 application。messages 收集制替代沿途 echo：单次 advance 内消息天然顺序产生，收尾一次性渲染即可保序，无分批问题。`GoalAdvanceStatus` 用 StrEnum 而非裸字符串常量——跨模块数据契约显名，`_GOAL_*` 常量在 cli_goal 保留为 `.value` 别名以兼容既有断言。

## Verification

- `python -m pytest tests/test_goal_declarative_workflow.py tests/test_story_loop.py tests/test_goal_cross_process_lock.py tests/test_gui_goal.py tests/test_wiring_loop_helpers.py tests/test_workflow_runner.py tests/test_artifact_contracts.py tests/test_architecture_contracts.py -q`（文件名以实际存在为准）
- `python scripts/quality_gate.py` 全量。
- `ruff check src tests scripts`、`ruff format --check src tests`、`mypy src`。

</frozen-after-approval>
