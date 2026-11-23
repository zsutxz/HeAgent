---
ticket: 3
ref: 75.3
code: E75-S03
epic: epic-75-project-channel-runtime
status: built
baseline_revision: 745b251a
risk: medium
hitl: false
covers: ["R1", "R2", "R7"]
---

# E75-S03 · `cli/ws_project_adapter.py` 帧转译单源

本 entry 交付 AD-2 / AD-6 / AD-7 的实现侧一半：`ProjectChannelService`（74.1 定义在
`network/ws_protocol.py`）的**入口层实现**。三个方法只做翻译——项目列表投影成 `WsProjectsFrame`、
提交收窄成 `SubmittedRun`、控制台/注册表稳定码逐字转成 `HttpRunConflictError`；判断全部留在
`cli/http_console.py` 与 `pub/projects.py`。装配（`build_ws_servers` 两处调用点、`cli/http.py`
注入同一个实例）与监听器侧的 WARNING 不在本 entry（75.5 / 75.6）。

## Tasks & Acceptance

- [x] 新增 `src/heagent/cli/ws_project_adapter.py::ProjectChannelAdapter`（**77 行**，entry 硬要求
      ≤150）：`__init__(console, registry_health)`；`list_projects()` / `start_project_run()` /
      `ensure_available()` 与端口签名逐字对齐。
- [x] `list_projects()`：`ProjectListResponse.projects` → `list[ProjectChannelEntry(id, name, available)]`，
      顺序沿用控制台给定顺序（= 注册表 `list()` 的倒序 + `default` 收尾）；`registry_state` 取
      `registry_health()`。
- [x] `start_project_run(project_id, prompt)`：唯一动作是
      `await console.start_project_run(project_id, ProjectRunRequest(prompt=prompt))` 并把
      `ProjectRunResponse` 收窄为 `SubmittedRun(run_id, status)`——`session_id` 不出入口层。
- [x] `ensure_available(project_id)`：成功原样返回 `project_id`（不占名额、不建 run、不写注册表）。
- [x] 错误码转译单点（`_conflict`）：`ConsoleOperationError.code` 与 `ProjectRegistryError.code`
      经 `HttpErrorCode(code)` **逐字**搬进 `HttpRunConflictError.code`，不改写、不折叠。
- [x] 适配器内不出现 `Path` / `is_dir` / `import os` / 注册表方法调用（`grep` 0 命中，另有源码级用例）。
- [x] 同批同步 `tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned` 白名单
      （`ws_project_adapter` 追加于 `wizard` 之后）与 `docs/framework.md` 的 cli 子模块表 + 目录树。
- [x] 新增 `tests/test_ws_project_adapter.py`（21 例，见「Verification」）。

## Design Notes

### bad_spec 记录：`docs/frame.md` 不存在（v6 命名遗留）

- **规格条目**：75.3 description 写「同批改 … `docs/frame.md` 的 cli 子模块表与目录树」。
- **实测**：`docs/frame.md` 在仓库里不存在（`docs/` 下只有 `framework.md` / `design.md` /
  `iteration.md` / `testing.md` / `sandbox.md` / `performance.md` / `errors.md` 等）。cli 子模块表与
  目录树住在 **`docs/framework.md` §4.1**（`| 子模块 | 职责 | 原文件 |` 表 +「六、目录结构」的
  `src/heagent/cli/` 段）。同一条错误也出现在 `architecture-ws-remote-project-channel.md` 的
  AD-8 与 §6 里。
- **处置**：按 `docs/framework.md` 同步（两处最小编辑），**不新建** `docs/frame.md`——建一份与
  `framework.md` 平行的 cli 表等于制造第二份真相，且会触发 mkdocs strict 的 nav 告警。
- **应改的规格条目**：75.3 description 的 `docs/frame.md` → `docs/framework.md`；epic 架构文档
  AD-8 与 §6 的同一处引用。

### 决策：`ensure_available` 借控制台的**纯读解析**读径，而不是在适配器里做成员判断

- 端口要求「未知 id / 目录失效」分别抛 `unknown_project` / `project_unavailable`，且**不占名额、
  不建 run、不写注册表**（R5）。
- `ConsoleHandler` 端口上唯一的纯读解析方法是 `get_project_config`：它第一步就是
  `_runtime_for(project_id)`，即在控制台里产 `unknown_project` / `project_unavailable` 的那条判据，
  之后只读配置（~14ms），不碰注册表写径。适配器因此只转发、不复制判断。
- **被拒替代**：读 `console.list_projects()` 再在适配器里判「id 在表里 + `available` 为真」——
  那会在入口层造出第二份项目判据（本 entry 的「只翻译不含判据」当场破功），且入参是**已投影**的
  响应模型，`available` 语义以后若加档位就会漂移。

### 决策：未登记的码不兜底

- AD-7 写「把注册表异常译成 `project_registry_unreadable`」；本 entry 的票面写「`ProjectRegistryError.code`
  **原样**包成」，两者在「注册表侧实际抛什么码」上不冲突：现存注册表码
  （`invalid_project_path` / `invalid_request` / `project_limit_reached` / `unknown_project` /
  `project_not_removable` / `server_error`）全部已是 `HttpErrorCode` 成员值，逐字搬运即得正确的 HTTP 码。
- 因此 `_conflict` **不做** `except ValueError: code = PROJECT_REGISTRY_UNREADABLE` 这类兜底：未登记的
  码让 `ValueError` 冒出（`StrEnum` 构造失败是响亮失败），连接骨架随后收敛成 `server_error` + 断连
  ——与 `ws_commands` 已声明的「漏译必须显性」同档。用例
  `test_unmapped_code_is_not_folded_into_a_generic_one` 钉住它。

### `RegistryState` 别名的理由

`WsProjectsFrame.registry_state` 是两值 `Literal`，而注入的探针是 `Callable`。适配器本地声明
`RegistryState = Literal["ok", "unreadable"]` 并把它同时用作注入类型与帧字段实参：静态上不需要
`cast`，运行期仍由 Pydantic 的 `Literal` 校验兜底（注入值不合规 → `ValidationError`，不静默折叠成
`ok`）。之所以不把它加到 `network/ws_protocol.py` 导出：本 entry 的 write_set 不含该文件，且网络层
已用内联 `Literal` 表达同一集合，扩 `__all__` 属于无收益的公开面增长。

## Code Map

| 文件 | 改动 |
|------|------|
| `src/heagent/cli/ws_project_adapter.py` | **新建**（77 行）：模块 docstring（只翻译 / 错误码纪律）+ `RegistryState` + `_conflict()` + `ProjectChannelAdapter` 三方法 |
| `tests/test_ws_project_adapter.py` | **新建**（21 例）：帧键集与顺序、可用性、健康态、提交收窄、错误码参数化（6 码 + 注册表码 + 未登记码）、前置校验（成功 / 三码转译）、端口签名反射、源码边界（禁用串 + AST 属性集）、行数预算 |
| `tests/test_architecture_contracts.py` | `test_cli_package_layout_is_pinned` 白名单 +1（`ws_project_adapter`）；改前该用例单点红、其余 39 例绿 |
| `docs/framework.md` | §4.1 cli 子模块表 +1 行；「六、目录结构」的 `cli/` 段把 `wiring.py` 由 `└──` 降为 `├──` 并追加 `ws_project_adapter.py` |

## Verification

实测命令与数字（2026-11-23，HEAD `745b251a`，venv `.heagent/tmp/py311-venv-linux`）：

| 命令 | 结果 |
|------|------|
| `pytest tests/test_ws_project_adapter.py -q` | **21 passed**（1.94s） |
| `pytest tests/test_architecture_contracts.py -q` | **40 passed**（12.51s；补白名单前为 1 failed / 39 passed，红点即 `test_cli_package_layout_is_pinned` 的 `Left contains one more item: 'ws_project_adapter'`） |
| `pytest tests -q -k "cli or architectural"` | **674 passed, 5182 deselected**（51.74s） |
| `python -m mkdocs build --strict` | 退出码 0，**WARNING 计数 0**（8.71s；输出里的「not included in nav」是既有 INFO 行） |
| `python -m ruff check src tests` | `All checks passed!`（首轮 1 错：TC003 `Callable` 未进类型检查块，已修） |
| `python -m ruff format --check src tests` | `503 files already formatted`（首轮 1 文件待格式化：列表推导折行，已按 ruff 口径并成一行） |
| `python -m mypy src` | `Success: no issues found in 240 source files` |
| `grep -n "Path\|is_dir\|import os" src/heagent/cli/ws_project_adapter.py` | **0 命中**（退出码 1） |
| `wc -l src/heagent/cli/ws_project_adapter.py` | **77**（entry 预算 ≤150） |

判据覆盖对照（票面 verify → 用例）：

- entry 序列化键集 == `{id,name,available}` 且 `"path"` 计数 0 →
  `test_projects_frame_entry_has_exactly_three_keys_and_no_path`。
- `SubmittedRun.model_fields` 不含 `session_id` →
  `test_start_project_run_narrows_to_submitted_run_without_session_id`。
- `ConsoleOperationError(code="project_busy")` / `ProjectRegistryError(code="project_registry_unreadable")`
  的 `HttpRunConflictError.code` 逐字相同 → `test_console_operation_error_code_passes_through_verbatim`
  （6 码参数化，含 `project_busy`）与 `test_project_registry_error_code_passes_through_verbatim`。
- `registry_health()` 回 `"unreadable"` ⇒ 帧 `registry_state == "unreadable"` →
  `test_projects_frame_carries_the_registry_health_state`（`ok` / `unreadable` 两值参数化）。

## 未闭合（gap）

- **`ensure_available` 的端到端行为未与真实 `HttpProjectConsole` 对跑**：本 entry 的替身是
  `ConsoleHandler` 项目面的最小鸭子类型，委托到 `get_project_config` 这一点只有源码 + 用例级证据；
  真实控制台的 `unknown_project` / `project_unavailable` 落点由 75.5 装配后的
  `tests/test_cli_http_lifecycle.py` 一族覆盖。
- **装配不在本 entry**：`cli/http.py` 两处 `build_ws_servers(...)` 尚未注入 `project_service`，
  因此 `projects` 命令在真实 listener 上仍回 `invalid_request`（活到 75.5）。

## 宿主复核（2026-11-23，串行门禁）

- `pytest tests/test_ws_project_adapter.py -q` → 21 passed（子会话与宿主同值）
- `pytest tests/network tests/test_architecture_contracts.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py tests/test_contract_baselines.py -q` → **778 passed, 1 warning**
- `ruff check src tests` / `ruff format --check src tests`（503 files）/ `mypy src`（**240** source files）/ `mkdocs build --strict`（子会话实测 0 warning）全绿
- 适配器 77 行（预算 ≤150）；`grep -n "Path\|is_dir\|import os" src/heagent/cli/ws_project_adapter.py` → 0 命中
- 宿主裁定：`ensure_available` 借 `ConsoleHandler.get_project_config` 的纯读解析（判据仍只有控制台一份）**采纳**；未登记码让 `ValueError` 冒出（漏译显性）**采纳**，不兜底成 `project_registry_unreadable`
