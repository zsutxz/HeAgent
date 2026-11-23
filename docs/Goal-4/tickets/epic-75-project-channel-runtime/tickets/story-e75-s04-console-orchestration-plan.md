---
ticket: 4
title: E75-S04 · 控制台编排：六项落点与会话续接/新建
status: built
baseline_revision: c232181b
covers: R3 / R4
risk: high
---

# E75-S04 · 控制台编排：六项落点与会话续接/新建

## Intent

`cli/http_console.py::HttpProjectConsole.start_project_run` 的编排语义要**可断言**，而不是靠读代码相信：

1. **会话二分是两条显式分支**：该项目有历史会话 ⇒ 续最近一次；从未有会话 ⇒ 新建。不是「查不到即异常」。
2. **六项落点全部锚定项目根**（不是控制台的启动工作区根）：
   `context.workspace_root`、会话文件、产物目录（状态根）、`ExecutionLedger` 行、
   `RunContext.state_root`（工具审计根）、memory 根；启动工作区根零新增产物、零新增 ledger 条目。
3. **`available=false` 的项目提交抛 `ConsoleOperationError(code="project_unavailable")`**，不建 run、不占名额。

本 entry 的重心是**判据**（NG12：不改写既有语义），实现侧只在实测发现真偏差时才动。

## Tasks & Acceptance

### 六项落点对账表（「谁决定根」）

| 落点 | 决定根的代码位置 | 结论 |
|------|------------------|------|
| `context.workspace_root` | `cli/http_console.py::_runtime_for` 的 `root = Path(entry.path)` → `Paths.from_root(root)` → `HttpAgentHandler.for_workspace` 把 `workspace_root=str(paths.root)` 传给派生 handler → `handler.engine = EngineContainer.default(workspace_root=str(paths.root), ...)` → `EngineContainer.create_run_context` 的 `root = self.workspace_root` 回退链 | 已正确（`<项目根>`） |
| 会话文件 | `_runtime_for` 的 `SessionStore(str(paths.sessions))`；`HttpAgentHandler.new_loop` 把它作为 `session=` 传给 `_build_loop` | 已正确（`<项目根>/.heagent/sessions/`） |
| 产物目录（状态根） | `pub/workspace.py::WorkspacePaths.state_dir` = `<root>/.heagent`（模块 docstring：「所有运行产物都在它下面」），根由 `_runtime_for` 的 `paths` 决定；后台任务投影 `configure_task_projection(paths.state_dir / "tasks")` 同源 | 已正确（`<项目根>/.heagent/`） |
| `ExecutionLedger` 行 | `EngineContainer.default` 的 `ledger=ExecutionLedger(base_dir=str(paths.ledger))`，`paths` 来自 `workspace_root` ⇒ `<项目根>/.heagent/ledger` | 已正确（`<项目根>/.heagent/ledger`） |
| `RunContext.state_root`（工具审计根） | `EngineContainer.create_run_context` 的 `product_root = self.workspace_root`（未显式传 `state_root` 时钉容器根，与 `run_store` / `ledger` 同源）；工具审计经 `ToolExecutor._audit_root_for()` 优先取它 | 已正确（`<项目根>`） |
| memory 根 | `HttpAgentHandler.__init__` 的 `FactStore(str(paths.memory_file))`（`paths` 由派生 handler 的 `workspace_root` 重算） | 已正确（`<项目根>/.heagent/memory/MEMORY.md`） |

**结论：六项落点零偏差，本轮不改 `cli/http_console.py`**（write_set 保留但未使用）。

### 会话二分对账

`_resolve_session`（`cli/http_console.py:809`）已是两条显式分支：

- `requested is not None` ⇒ `_guarded_session_id` + `load_metadata`（`None` ⇒ `unknown_session`、解析失败 ⇒ `session_unreadable`），**不改写**；
- 缺省 ⇒ 遍历 `list_metadata()`（时间降序）取第一条 `unreadable=False` 的会话 id **复用**；全部不可用 / 无会话时 `uuid.uuid4().hex` **新建**并 `sessions.create`。

腐蚀文件不会被当成「空会话」覆盖（AC9 的 `unreadable` 过滤）。已正确，本轮不改。

### 本轮产出

- 新增 `tests/test_http_console_project_run.py`：单项目 / 两项目各一例（六项落点 + 启动工作区零新增）、会话二分两例、`available=false` 一例。

## Design Notes

- **判据用真运行时，不用假 handler**：`handler_factory` 注入的是真 `HttpAgentHandler.for_workspace`
  （`sandbox_backend="passthrough"` 显式压住仓库 `.env` 的 docker 档，避免测试里探测 daemon）。
  只有真 handler 才带 `engine` / `facts` / `paths`，六项落点才有实物可断言；假 handler 只能断言
  「控制台把 session_id 传下去了」，证不到根。
- **真跑一次 run**：`HttpRunService` 起后台任务 → 真 `AgentLoop` + 脚本化 provider ⇒ 会话文件由运行
  收尾真实落盘。这比「断言 `paths.sessions` 字符串」强一档：落点错根的现象正是「文件写到别处」。
- **`state_root` / `workspace_root` 取自容器自己的 `create_run_context()`**，而不是自己拼字符串——
  它就是工具审计与路径围栏的取值来源。
- **启动工作区零新增的口径**：控制台自己的项目登记表必然写在启动工作区（`<ws>/.heagent/console/`），
  所以基线快照取在**登记项目之后、提交运行之前**；随后断言 `runs` / `sessions` / `ledger` / `memory`
  四个目录在启动工作区**不存在**，且文件集合与基线逐项相等。
- **`available=false` 的「不占名额」**用 `service.active_runs == 0` + 无新增文件作判据（不引入对
  `start_run` 的 monkeypatch 缝）。

## Code Map

| 文件 | 角色 |
|------|------|
| `src/heagent/cli/http_console.py` | `start_project_run`（`:642`，守卫 → `_resolve_session` → `runs.start_run` → `_touch`）、`_runtime_for`（`:794`，根/会话/executor 单点解析）、`_resolve_session`（`:809`，会话二分）、`HttpAgentHandler.for_workspace`（`:253`，per-project settings/engine/memory） |
| `src/heagent/engine/container.py` | `EngineContainer.default`（`:320`，`run_store` / `ledger` 按 `paths` 落根）、`create_run_context`（`:450`，`workspace_root` / `state_root` 回退链） |
| `src/heagent/pub/workspace.py` | `WorkspacePaths`（`state_dir` / `sessions` / `ledger` / `runs` / `memory_file` 的唯一定义） |
| `src/heagent/network/http_server.py` | `HttpRunService.start_run` / `active_runs` / `close`（名额与在途事实单点） |
| `tests/network/test_http_console_sessions.py` | 只读参考：`_Harness` 形态、`start_project_run` 调用样例（`:694`、`:750`） |
| `tests/test_http_console_project_run.py` | **本轮新增**判据 |

## Verification（实测，2026-11-23，baseline `c232181b`）

```
.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_http_console_project_run.py -q
  → 5 passed in 2.14s
.heagent/tmp/py311-venv-linux/bin/python -m pytest tests -q -k http_console
  → 128 passed, 5733 deselected in 13.18s（NG12：既有项目链语义未改写）
.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q
  → 706 passed, 1 warning in 22.47s
.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests
  → All checks passed!
.heagent/tmp/py311-venv-linux/bin/python -m ruff format --check src tests
  → 504 files already formatted
.heagent/tmp/py311-venv-linux/bin/python -m mypy src
  → Success: no issues found in 240 source files
```

新增用例 5 条：

| 用例 | 断言面 |
|------|--------|
| `test_single_project_run_lands_entirely_inside_the_project_root` | 六项落点 + 启动工作区零新增 + ledger 行真落项目根 |
| `test_two_projects_each_land_in_their_own_root` | 两项目各自落根 + 跨项目不串味 + 启动工作区零新增 |
| `test_existing_session_is_continued_instead_of_starting_a_new_one` | 有历史会话 ⇒ `session_id` 复用、会话文件仍只有一条 |
| `test_project_without_history_creates_a_new_session` | 无历史 ⇒ 新 `session_id`，且与另一项目历史 id 不同 |
| `test_unavailable_project_is_rejected_without_creating_a_run` | `project_unavailable` + `active_runs == 0` + 零新增文件 |

## Gaps

## Gaps

- 工具审计**文件**（`<state_root>/audit/…`）本轮不真跑工具：判据停在「`RunContext.state_root` 指向项目根」
  （即审计根的取值来源），未断言真实审计写入。理由：需要脚本化工具调用 + 沙箱/审计配置，
  属 E75-S03/S05 的工具面覆盖。
- Linux 容器内无法验证 Windows 路径形态（`\\?\`、大小写折叠）对 `Path.resolve()` 比较的影响：
  判据用 `Path(...).resolve()` 两侧归一，跨平台口径未实测。

## 宿主复核（2026-11-23，串行门禁）

- `pytest tests/test_http_console_project_run.py -q` → **5 passed**（子会话与宿主同值）
- `pytest tests/test_http_console_project_run.py tests/network tests/test_architecture_contracts.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py -q` → **778 passed, 1 warning**
- `pytest tests -q -k http_console` → 128 passed（子会话实测）；`ruff check` / `ruff format --check`（504 files）/ `mypy src`（240 files）全绿
- 六项落点对账结论**全部「已正确」**，`src/heagent/cli/http_console.py` 零改动（NG12：不改写既有 HTTP 项目链语义）
- 采纳其关键取舍：用真 `HttpAgentHandler.for_workspace` + 真 `AgentLoop`（`sandbox_backend="passthrough"`）跑一次，避免「只证明字符串拼得对」的假断言；ledger 用 `engine.ledger.acquire(...)` 真写一行
