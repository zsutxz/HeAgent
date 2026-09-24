---
id: 50-1
title: 工作区一等化与状态根单一来源
status: ready-for-dev
parent_epic: E50
priority: P0
phase: A（工作区基础）
depends_on: []
blocks: [50-2, 50-3, 50-4, 50-5, 50-6, 50-7]
created: '2026-09-23'
---

# Story 50-1：工作区一等化与状态根单一来源

## 用户故事

作为 HeAgent 维护者，我希望「工作区」成为一等参数、且所有运行态路径都从它派生，以便同一个 HTTP 服务进程
能安全地服务多个项目而不串味（会话 / 记忆 / 技能 / 运行快照 / 围栏基址都不落到进程 cwd 上）。

本 story 是 Epic 50 的地基：50-2..50-6 的每一个能力都要把「项目」翻译成一组路径与一个围栏根，
翻译规则在此单点定义。

## 侦察实证（本 story 全部改动的依据，2026-09-23 实测）

| 事实 | 证据 | 本次实测方式 |
|---|---|---|
| 有 **8** 处 `os.getcwd()` 装配点，散在 4 个入口模块 | `cli.py:219,243,263,313,460`；`cli_goal.py:340`；`cli_http.py:197`；`cli_tcp.py:170` | `git grep -n "os.getcwd()" src/heagent` |
| `RunStore` / `ExecutionLedger` **无注入面** | `EngineContainer` 是 `@dataclass`，`run_store: RunStore = field(default_factory=RunStore)`（`engine/container.py:44-45`）→ 无参构造 ⇒ `.heagent/runs`、`.heagent/ledger`（cwd 相对） | 读 `container.py:38-66`；`git grep -n "RunStore(" src/heagent` 无命中 |
| `EngineContainer.default()` **已经**接受 `workspace_root=`，但它只喂给 policy 与沙箱会话目录，**不**喂给 run_store/ledger | `container.py:173-176`（形参）、`243`（转交构造）、`303-304`（policy）、`313-341`（沙箱会话目录） | 读 `container.py:196-341` |
| 工具围栏**已经**按 run 参数化，不需要新机制 | `agent/loop.py:651` `create_run_context(..., workspace_root=self.context_dir)` → `agent/loop.py:676` `bind_workspace_root(Path(run_context.workspace_root))`；`engine/policy.py:313-315` 优先取 `context.workspace_root` | 读 `loop.py:640-700`、`policy.py:268-320` |
| **两层围栏可能锚到不同的根**：policy 层「二者皆空则放行」，handler 层退回 cwd | `engine/policy.py:288-290`（`root is None → return ""`）；`tools/path_safety.py:87`（`resolve_under_root(path, workspace_root())`，`workspace_root()` 兜底 cwd，见 `:56-62`） | 读两处实现 |
| 已有现成的 per-context 注入原语 | `tools/path_safety.py:37` `_workspace_runtime = RuntimeSlot[Path](...)`；`:180` `configure_workspace_root()`；`:186` `bind_workspace_root()`；当前 `src/` 内唯一调用者是 `agent/loop.py:676` | `git grep -n "configure_workspace_root\|bind_workspace_root"` |
| `AgentLoop.context_dir` 默认 `None`，而 `None` 会让 policy 层围栏放行 | `agent/loop.py:142`（默认值）、`:204`、`:207`；GUI 显式传 `context_dir=None`（`gui/__init__.py:78,115`） | 读 `loop.py:193-215`；`git grep -n "context_dir"` |
| 内部状态读拒只覆盖 **5** 个子目录 | `tools/path_safety.py:248-261`：`Path.cwd()`+`Path.home()` + `("sessions","ledger","runs","memory","skills")` | 读 `path_safety.py:238-261` |
| 全部既有 store 已是「路径形参」形态（改造面 = 装配点传参） | `context/session.py:82`；`memory/skill_store.py:47`；`memory/facts.py:41`；`memory/profile.py:21`；`cron/jobs.py:36`；`engine/store.py:91`；`engine/ledger.py:122`；`engine/checkpoint.py:85`；`tools/edits.py:136` | `git grep -nE "base_dir: str = \|path: str = "` |

> **校正**：`epics.md` 与 `ARCHITECTURE-SPINE.md` 原写「`EngineContainer.default()` 必须**新增**状态根形参」。
> 实测 `workspace_root=` 形参早已存在，**缺的是把它接到 `run_store` / `ledger`**。见本 story 的 T3 与
> `ARCHITECTURE-SPINE.md` §14 校正表。

## 范围

- 新增顶层模块 `src/heagent/workspace.py`：`WorkspacePaths`（frozen Pydantic），`root` → 全部运行态路径的单点派生。
- `tools/path_safety.build_internal_state_dirs()` 改为接受工作区根（缺省保持既有语义），返回集合从同一来源派生，
  并补齐运行态子目录（`user` / `cron` / `checkpoints` / `sandboxes` / `tmp/edit-snapshots` / `console` / `backups`）。
- `EngineContainer.default()` 把 `workspace_root` 接到 `run_store` / `ledger`（新增可选状态根形参亦可，二者择一，见 T3）。
- 全部 store 装配点（`cli.py` / `cli_http.py` / `cli_tcp.py` / `cli_goal.py` / `gui`）改为经 `WorkspacePaths` 传参。
- `AgentLoop.context_dir` 在所有装配点恒为**具体项目根**；禁止再出现 `context_dir=None` 的多项目路径。
- 架构契约测试钉住：`os.getcwd()` 装配点白名单（只允许入口层兜底），且 `WorkspacePaths` 是路径字符串的单一来源。

## 边界与约束

**Always**

- 路径只从 `WorkspacePaths` 派生；`root` 一旦绑定（`resolve()` 后）不再读进程状态。
- 缺省参数保持既有语义：未传工作区的调用方（CLI / GUI / TCP）行为与改造前**逐字节等价**（I13 无回归）。
- `WorkspacePaths` 保持 `frozen`，字段全部为 `Path`；不引入可变的「当前工作区」全局变量。
- 围栏两层（policy 预检 + handler 守卫）在**同一次运行内**锚到同一个根，并留测试钉住这一点。

**Never**

- 不 `os.chdir()`、不改 `os.environ`（I3）。
- 不做「进程级当前项目」可变状态；项目身份只经参数传递。
- 不在既有 store 里再写第二份路径拼接（如 `Path(base) / ".heagent" / "sessions"`）。
- 不让 `WorkspacePaths` 导入任何 heagent 模块（除 stdlib；见脊柱 §2 的依赖表）。
- 不把 `build_internal_state_dirs()` 的收紧做成「顺手扩大 deny 导致误伤」——工作区内普通文件必须仍可读。

## 任务（细分）

- [ ] **T1** 新建 `src/heagent/workspace.py`：`WorkspacePaths`（`frozen=True`）以 `root` 为唯一输入派生
      12 条路径（`state_dir`/`sessions`/`skills`/`memory_file`/`profile_file`/`cron_file`/`runs`/`ledger`/
      `checkpoints`/`sandboxes`/`edit_snapshots`/`console_dir`/`config_backups`/`projects_file`），
      并提供一个把 `root` 归一为 `resolve()` 绝对路径的构造校验（`field_validator`）。
- [ ] **T2** `build_internal_state_dirs(workspace_root: str | Path | None = None)`：`None` 时保持
      `(cwd, home)` 双根语义；显式传入时从 `WorkspacePaths` 派生并覆盖 12 个子目录（I14）。同步更新 docstring
      （现文案说「与 session/ledger/store/memory/skills 的默认 base_dir 一致」——收紧后不再只是这 5 个）。
- [ ] **T3** `EngineContainer.default()`：把解析出的 `workspace_root` 落到 `run_store`/`ledger` 实例
      （`RunStore(base_dir=paths.runs)` / `ExecutionLedger(base_dir=paths.ledger)`）；`None` 时保持
      `default_factory` 现状。**同时**核对 `container.workspace_root` 与 `policy.workspace_root` 同值（`:303-304`）。
- [ ] **T4** 装配点替换：`cli.py`（5 处）、`cli_http.py:197`、`cli_tcp.py:170`、`cli_goal.py:340` 全部改为
      从该入口自己的 `WorkspacePaths` 取值；`os.getcwd()` 只允许出现在 `WorkspacePaths` 的缺省构造处（入口层兜底）。
- [ ] **T5** store 装配：`SkillStore` / `FactStore` / `ProfileStore` / `SessionStore` / `JobStore` /
      `WorkflowCheckpointStore` 的构造点改为传 `WorkspacePaths` 派生路径（含 `cli_http` 的 handler 与 `cli._build_loop` 的 `cron_store`）。
- [ ] **T6** `edit_snapshots`：`tools/edits.py:136/144` 现走 `workspace_root()`（cwd 兜底）；改为优先使用已绑定
      run 的路径，保持 `bind_edit_snapshot_run` 语义不变。
- [ ] **T7** `AgentLoop.context_dir`：所有多项目路径必须传具体根；新增断言/测试禁止 `context_dir=None` 从
      `cli_http` / `cli_console` 进入（GUI 的 `None` 语义保留并记录为既有行为，见「风险与未决」R2）。
- [ ] **T8** 测试：跨工作区隔离（同一进程先后装配 `W1`/`W2`，写技能/事实/会话/运行快照后互不可见）、
      `chdir` 后围栏与状态根仍锚定绑定工作区、deny 集合新增子目录逐条读拒、工作区内普通文件仍可读（不误伤）、
      「两层围栏同根」断言。
- [ ] **T9** 架构契约测试：`tests/test_architecture_contracts.py` 增加
      ① `os.getcwd()` 装配点白名单（超集即失败）；② `WorkspacePaths` 是路径字符串单一来源（禁止新增
      `".heagent/<sub>"` 字面量拼接）；③ `workspace.py` 的导入面只有 stdlib + pydantic。
- [ ] **T10** 负向验证：临时回退 T2 的收紧项（`subdirs` 退回 5 个）与 T3 的接线（恢复 `default_factory`），
      确认 T8/T9 新增测试**逐条变红**，然后复原。

## 验收标准

- **AC1** Given 一个显式工作区 `W`，When 用 `W` 组装 engine 与各 store，Then 运行态根（sessions / skills /
  memory / user / cron / runs / ledger / checkpoints / sandboxes / edit-snapshots / console / backups）
  **全部**位于 `W/.heagent/` 之下，且没有任何一条落在进程 cwd 下。
- **AC2** Given 同一进程先后装配 `W1` 与 `W2`，When 分别写入技能 / 事实 / 会话 / 运行快照，Then 两侧文件互不出现，
  且 `W1` 的 `SkillStore` 看不到 `W2` 的技能。
- **AC3** Given 已绑定的工作区 `W`，When 进程执行 `os.chdir(其它目录)`，Then 围栏基址、上下文发现目录与状态根
  **仍然一致**（不出现「构造期冻结 vs 每 run 重读」的分叉）。
- **AC4** Given 工作区 `W`，When 通过文件工具读取 `W/.heagent/{user,cron,checkpoints,tmp/edit-snapshots,sandboxes,console,backups}`
  中的任一文件，Then 被内部状态读拒拦下；而 `W` 内普通文件仍可读（不误伤）。
- **AC5** Given 一次多项目装配的运行，When 该运行执行受围栏约束的文件工具，Then policy 预检与 handler 守卫
  使用**同一个**根（同根断言），且该根等于项目根而非 cwd。
- **AC6** Given 未显式传入工作区的既有调用方（CLI / GUI / TCP），When 装配运行，Then 行为与改造前一致
  （回退到进程 cwd），既有测试无回归。

## Definition of Done

**交付物**：`src/heagent/workspace.py`（新）、`tools/path_safety.py`、`engine/container.py`、`agent/loop.py`、
`cli.py`、`cli_http.py`、`cli_tcp.py`、`cli_goal.py`、`gui/__init__.py`（按需）、`tests/test_workspace_paths.py`（新）、
`tests/test_credential_guard.py`、`tests/test_architecture_contracts.py`。

**验证命令**（本机 2026-09-23 实测存在性已核对；`tests/test_path_safety.py` **不存在**，勿沿用旧 epics.md 的写法）：

```bash
pytest tests/test_workspace_paths.py tests/test_credential_guard.py tests/test_engine_p0.py tests/test_session.py -q
pytest tests/test_architecture_contracts.py tests/test_config.py -q
pytest -q                     # 全量回归（覆盖率门槛 87%）
ruff check src tests
mypy src
mypy src --platform linux     # 本地必跑双平台（CI 是 ubuntu + py3.11）
```

**负向验证**：T10 的两项回退各自精确变红（记录失败测试名与断言行）。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/workspace.py` | **新增**；`WorkspacePaths` 单一来源 | 全部路径派生 + `frozen` 校验 |
| `src/heagent/tools/path_safety.py` | deny 集合 + 围栏原语 | `build_internal_state_dirs()` 接工作区根；子目录 5 → 12 |
| `src/heagent/engine/container.py` | 装配 `run_store`/`ledger` | `default()` 把 `workspace_root` 接到实例（`init` 字段已具名） |
| `src/heagent/agent/loop.py` | 每 run 绑定围栏根 | `context_dir` 必须为具体根（`:142/204/207/651/676`） |
| `src/heagent/cli.py` / `cli_http.py` / `cli_tcp.py` / `cli_goal.py` | 装配点 | 8 处 `os.getcwd()` → `WorkspacePaths` |
| `src/heagent/context/session.py` 等 9 个 store | 路径形参已具备 | 仅装配点传参，不改内部实现 |
| `tests/test_workspace_paths.py` | **新增** | AC1–AC5 的定向测试 |
| `tests/test_architecture_contracts.py` | 契约测试 | `os.getcwd()` 白名单 + 路径字面量禁令 |

## 风险与未决

- **R1（已定）**：`WorkspacePaths.edit_snapshots` 与 `tools/edits.py` 的 `SNAPSHOT_DIRNAME` 存在两处表达；
  本 story 要求 `edits.py` 以 `WorkspacePaths` 为准，但 `bind_edit_snapshot_run` 的 ContextVar 语义保持不动。
- **R2（记录，不在本 story 修）**：GUI 目前显式传 `context_dir=None`（`gui/__init__.py:78,115`），
  意味着 GUI 的 policy 层围栏「放行」而 handler 层退回 cwd。这是既有行为，**不在 Epic 50 范围**；
  本 story 只要求不引入新的 `None` 路径，并在 frame.md 如实记录。
- **R3**：`housekeeping.py` 是否有重复拼串需在实现时核对（侦察未逐行确认，标为待查，不得当作已知为零）。
- **R4**：`settings.workspace_root`（`ResolvedRuntimeConfig` 字段，`config.py:539`）与新 `WorkspacePaths` 的关系
  必须在实现中定死：**入口层构造 `WorkspacePaths` 并回填 `ResolvedRuntimeConfig.workspace_root`**，不允许两处各算一次。

## Requirement Traceability

FR-1；NFR-1, NFR-2, NFR-8, NFR-10；脊柱 I2, I3, I13, I14；brief §3 硬结论 (a)、§6.6、§6.7。
