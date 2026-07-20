---
cycle: sandbox-hardening
epic: S2
story: S2-2
status: backlog
depends_on: S1-1
---

# Story S2-2: .env / CLI 配置入口 + EngineContainer.default() 自动构造 runner

## Story

As a HeAgent 操作者,
I want 通过 `.env` 变量或 CLI flag 启用 firejail 沙箱,
So that 我不需要写 Python 代码就能开启沙箱功能。

> 依赖 S1-1（`FirejailBackend` 新构造参数已存在）。本 story 让 CLI 和 `.env`
> 能驱动 `EngineContainer.default()` 自动构造正确的 runner。

## Acceptance Criteria

**AC-1（FR-S4 Settings 新字段）**
**Given** `config.py` `Settings` 新增：
- `sandbox_backend: Literal["passthrough", "firejail"] = "passthrough"`
  （来自 `SANDBOX_BACKEND` 环境变量，alias=`sandbox_backend`）
- `sandbox_firejail_path: str = "firejail"`
  （来自 `SANDBOX_FIREJAIL_PATH` 环境变量，alias=`sandbox_firejail_path`）

**When** `.env` 中 `SANDBOX_BACKEND=firejail`
**Then** `get_settings().sandbox_backend` 为 `"firejail"`

**AC-2（FR-S4 CLI flag 优先）**
**Given** CLI `main()` 新增 `--sandbox` option（`type=click.Choice(["passthrough", "firejail"])`，default `"passthrough"`）
**When** `heagent --sandbox firejail "echo hi"`
**Then** CLI flag 覆盖 `.env` 的 `SANDBOX_BACKEND` 值

**AC-3（FR-S4 EngineContainer.default() passthrough 路径）**
**Given** 最终生效的 `sandbox_backend` 为 `"passthrough"`
**When** `EngineContainer.default(workspace_root="...")`
**Then** `command_runner=None`（保持 executor `execute_in_sandbox` 的 `if None` 快速路径）

**AC-4（FR-S4 EngineContainer.default() firejail 路径）**
**Given** `sandbox_backend` 为 `"firejail"`
**When** `EngineContainer.default(workspace_root="...")`
**Then** `command_runner=FirejailBackend(firejail_path=settings.sandbox_firejail_path, workspace_root=workspace_root)`

**AC-5（不变量）**
**Given** `EngineContainer.default()` 产生的 container
**When** `__post_init__` 执行
**Then** 既有守卫逻辑不变：`executor.sandbox_runner is None` 时才注入 container 级 runner

## Tasks

- [ ] **Task 1: Settings 新字段** (AC-1)
  - [ ] `config.py` `Settings` 新增 `sandbox_backend`（`Literal["passthrough", "firejail"]`，default `"passthrough"`）
  - [ ] 新增 `sandbox_firejail_path`（`str`，default `"firejail"`）
  - [ ] `Field(validation_alias=...)` 支持 `SANDBOX_BACKEND` / `SANDBOX_FIREJAIL_PATH` env 变量

- [ ] **Task 2: CLI --sandbox flag** (AC-2)
  - [ ] `cli.py` `main()` 新增 `@click.option("--sandbox", type=click.Choice(["passthrough", "firejail"]), default="passthrough", ...)`
  - [ ] `_run_single` / `_run_chat` 签名新增 `sandbox_backend: str` 参数
  - [ ] CLI flag 覆盖 `settings.sandbox_backend`：`if sandbox != "passthrough": settings.sandbox_backend = sandbox`

- [ ] **Task 3: EngineContainer.default() 读 Settings** (AC-3, AC-4, AC-5)
  - [ ] `container.py` `EngineContainer.default()` 新增参数 `sandbox_backend: str | None = None`
  - [ ] 传了 sandbox_backend 就用它；否则从 `get_settings().sandbox_backend` 取
  - [ ] `"passthrough"` → `command_runner=None`
  - [ ] `"firejail"` → `command_runner=FirejailBackend(firejail_path=settings.sandbox_firejail_path, workspace_root=workspace_root)`
  - [ ] `__post_init__` 不变——仅当 `executor.sandbox_runner is None` 时注入

- [ ] **Task 4: CLI 接入** (AC-2)
  - [ ] `_build_loop` 签名新增 `sandbox_backend: str | None = None`
  - [ ] `_build_loop` 内 `engine = engine or EngineContainer.default(..., sandbox_backend=sandbox_backend)`
  - [ ] `_run_single` / `_run_chat` 把 sandbox_backend 传下去

- [ ] **Task 5: 测试** (AC-1~5)
  - [ ] `test_sandbox_backend_default_passthrough`：Settings 默认值断言
  - [ ] `test_sandbox_backend_from_env`：mock env `SANDBOX_BACKEND=firejail`
  - [ ] `test_sandbox_firejail_path_from_env`：mock env `SANDBOX_FIREJAIL_PATH=/usr/bin/firejail`
  - [ ] `test_cli_flag_overrides_env`：CLI `--sandbox firejail` 覆盖 `.env`
  - [ ] `test_container_default_passthrough`：`sandbox_backend="passthrough"` → `executor.sandbox_runner is None`
  - [ ] `test_container_default_firejail`：`sandbox_backend="firejail"` → `isinstance(executor.sandbox_runner, FirejailBackend)`
  - [ ] `test_container_post_init_guard_preserved`：executor 已有 runner 时不覆盖
